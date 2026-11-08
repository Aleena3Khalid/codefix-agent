"""Turn a bug report into a diagnosis and a proposed fix.

Steps:
1. Scan the repo and pick the functions most related to the issue (Day 1 analyser).
2. Optionally run the tests, so the model sees the real failure messages (Day 1 test runner).
3. Ask the LLM for a structured diagnosis through a forced tool call.
4. Check the answer: does the function exist, and does the proposed code parse?
"""

from __future__ import annotations

import ast
import textwrap
from dataclasses import dataclass, field

from codefix.analyzer import ScanResult, get_function_source, scan_repository, search_functions
from codefix.llm import LLM, Usage
from codefix.test_runner import TestReport, run_tests

SYSTEM_PROMPT = """You are a careful Python debugging assistant.
You receive a bug report, the source of the functions most likely involved, and
sometimes the output of the failing tests.
Find the root cause and propose the smallest change that fixes it.
Rules:
- Change only one function, the one that contains the bug.
- Keep its name, arguments and docstring the same.
- Do not change tests.
- If the code shown is not enough to be sure, say so and set confidence to "low".
Answer only by calling the submit_diagnosis tool."""

# The JSON schema tells the model exactly which fields to return and their types.
DIAGNOSIS_TOOL = {
    "name": "submit_diagnosis",
    "description": "Submit the diagnosis of the bug and the proposed fix.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "One sentence: what is wrong."},
            "file": {"type": "string", "description": "File containing the bug, e.g. cart.py"},
            "function": {"type": "string", "description": "Name of the buggy function, e.g. apply_discount or Cart.add"},
            "root_cause": {"type": "string", "description": "Why the code produces the wrong result."},
            "fixed_code": {"type": "string", "description": "The complete corrected function, from the def line to its last line."},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        },
        "required": ["summary", "file", "function", "root_cause", "fixed_code", "confidence"],
    },
}


@dataclass
class Diagnosis:
    summary: str
    file: str
    function: str
    root_cause: str
    fixed_code: str
    confidence: str
    usage: Usage | None = None
    warnings: list[str] = field(default_factory=list)  # problems found when checking the answer

    def to_dict(self) -> dict:
        data = {k: v for k, v in self.__dict__.items() if k != "usage"}
        data["usage"] = self.usage.to_dict() if self.usage else None
        return data


def build_prompt(issue: str, scan: ScanResult, top_k: int = 3, test_output: str | None = None) -> str:
    """Assemble the user message: issue, candidate functions, and optional test output."""
    matches = [func for func, _ in search_functions(scan, issue, limit=top_k)]
    if not matches:
        # Keyword search found nothing: fall back to every function (fine for small repos).
        matches = scan.source_functions()[:10]

    parts = [f"## Bug report\n{issue.strip()}", "## Candidate functions"]
    for func in matches:
        source = get_function_source(scan.root, func)
        parts.append(f"### {func.file} :: {func.qualified_name} (lines {func.start_line}-{func.end_line})\n```python\n{source}\n```")
    if test_output:
        parts.append(f"## Output of the failing tests\n```\n{test_output.strip()}\n```")
    return "\n\n".join(parts)


def check_diagnosis(diag: Diagnosis, scan: ScanResult) -> list[str]:
    """Never trust model output blindly. Return a list of problems (empty if it looks fine)."""
    warnings = []
    known = {(f.file, f.qualified_name) for f in scan.source_functions()}
    if (diag.file, diag.function) not in known:
        warnings.append(f"Function {diag.function!r} in {diag.file!r} was not found in the repository.")
    
    if not diag.fixed_code.strip():
        warnings.append("fixed_code is empty. Put the complete corrected function in the fixed_code field.")
        return warnings    

    try:
        # dedent first: for a method, the model may return the code still indented
        # as it is inside the class. The patcher re-indents it anyway.
        tree = ast.parse(textwrap.dedent(diag.fixed_code))
    except SyntaxError as exc:
        warnings.append(f"Proposed code does not parse: {exc}")
        return warnings

    defs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    expected_name = diag.function.split(".")[-1]
    if len(defs) != 1 or defs[0].name != expected_name:
        warnings.append(f"Proposed code should contain exactly one function named {expected_name!r}.")
    return warnings


def diagnose(
    repo: str,
    issue: str,
    llm: LLM | None = None,
    top_k: int = 3,
    include_tests: bool = True,
    test_report: TestReport | None = None,
    feedback: str | None = None,
) -> Diagnosis:
    """Ask the LLM for a diagnosis.

    test_report: reuse a test run you already have instead of running the tests again.
    feedback:    text about a previous attempt that failed (used by the repair loop).
    """
    scan = scan_repository(repo)
    test_output = None
    if include_tests:
        report = test_report or run_tests(repo)
        if not report.all_passed:
            test_output = report.output

    llm = llm or LLM()
    prompt = build_prompt(issue, scan, top_k=top_k, test_output=test_output)
    if feedback:
        prompt += "\n\n" + feedback.strip()
    answer, usage = llm.call_tool(SYSTEM_PROMPT, prompt, DIAGNOSIS_TOOL)

    diag = Diagnosis(**{key: answer.get(key, "") for key in DIAGNOSIS_TOOL["input_schema"]["required"]})
    diag.usage = usage
    diag.warnings = check_diagnosis(diag, scan)
    return diag