"""The repair loop: issue -> diagnosis -> patch -> tests -> (retry) -> approval -> apply.

Safety rules:
- Every proposed patch is tested in a sandbox: a temporary copy of the repo.
  The real repo is never touched while the agent is experimenting.
- The number of attempts is limited (max_attempts), so a confused model cannot loop forever.
- The real repo is changed only after a patch has passed the tests in the sandbox
  AND a human has approved the diff.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from codefix.analyzer import get_function_source, scan_repository
from codefix.assistant import Diagnosis, diagnose
from codefix.llm import LLM
from codefix.patcher import Patch, PatchError, apply_patch, make_patch
from codefix.test_runner import TestReport, run_tests

SANDBOX_IGNORE = shutil.ignore_patterns(".git", ".venv", "venv", "__pycache__", ".pytest_cache", "runs", "node_modules")

# approve(patch, attempt) -> True to apply the patch to the real repo
Approver = Callable[[Patch, "Attempt"], bool]


@dataclass
class Attempt:
    number: int
    diagnosis: Diagnosis | None = None
    patch: Patch | None = None
    error: str | None = None            # why no patch could be tested, if so
    report: TestReport | None = None    # test results in the sandbox
    fixed: list[str] = field(default_factory=list)        # failed before, pass now
    regressions: list[str] = field(default_factory=list)  # passed before, fail now
    still_failing: list[str] = field(default_factory=list)  # related tests that still fail
    success: bool = False

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "diagnosis": self.diagnosis.to_dict() if self.diagnosis else None,
            "patch": self.patch.to_dict() if self.patch else None,
            "error": self.error,
            "report": self.report.to_dict() if self.report else None,
            "fixed": self.fixed,
            "regressions": self.regressions,
            "still_failing": self.still_failing,
            "success": self.success,
        }


@dataclass
class FixResult:
    repo: str
    issue: str
    status: str = "failed"  # fixed | fixed_not_applied | failed | nothing_to_fix
    baseline: TestReport | None = None
    attempts: list[Attempt] = field(default_factory=list)
    applied: bool = False
    final_report: TestReport | None = None  # tests on the real repo after applying
    duration_s: float = 0.0

    @property
    def winning_attempt(self) -> Attempt | None:
        return next((a for a in self.attempts if a.success), None)

    def totals(self) -> dict:
        usages = [a.diagnosis.usage for a in self.attempts if a.diagnosis and a.diagnosis.usage]
        costs = [u.cost_usd for u in usages]
        return {
            "llm_calls": len(usages),
            "input_tokens": sum(u.input_tokens for u in usages),
            "output_tokens": sum(u.output_tokens for u in usages),
            "cost_usd": None if None in costs else round(sum(costs), 6),
            "llm_latency_s": round(sum(u.latency_s for u in usages), 3),
        }

    def to_dict(self) -> dict:
        return {
            "repo": self.repo,
            "issue": self.issue,
            "status": self.status,
            "applied": self.applied,
            "duration_s": self.duration_s,
            "totals": self.totals(),
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "attempts": [a.to_dict() for a in self.attempts],
            "final_report": self.final_report.to_dict() if self.final_report else None,
        }


def test_id(func) -> str:
    """pytest id of a test function, e.g. tests/test_cart.py::test_apply_discount."""
    return f"{func.file}::{func.qualified_name.replace('.', '::')}"


def related_tests(scan, failing: list[str], function: str) -> list[str]:
    """Failing tests whose code mentions `function` by name.

    A simple, transparent link between a function and its tests. It misses tests that
    only reach the function indirectly, which is why it is only one part of the rule.
    """
    name = function.split(".")[-1]
    pattern = re.compile(rf"\b{re.escape(name)}\b")
    sources = {test_id(f): get_function_source(scan.root, f) for f in scan.test_functions()}
    return [t for t in failing if pattern.search(sources.get(t, ""))]


def compare_reports(before: TestReport, after: TestReport, targets: list[str]) -> tuple[list[str], list[str], list[str], bool]:
    """Return (fixed, regressions, still_failing, success).

    targets: the failing tests that use the patched function (see related_tests).

    success means all of these:
    - at least one failing test now passes,
    - every target test now passes (a partial fix is not a fix),
    - nothing that passed before fails now (no regressions),
    - the run did not time out,
    - no tests disappeared. If a patch breaks an import, a whole test file stops being
      collected and its failing tests vanish from the list. A test that disappears is
      not a fixed test.
    """
    before_failed, after_failed = set(before.failed_tests), set(after.failed_tests)
    fixed = sorted(before_failed - after_failed)
    regressions = sorted(after_failed - before_failed)
    still_failing = sorted(set(targets) & after_failed)
    vanished = after.total < before.total
    success = bool(fixed) and not still_failing and not regressions and not after.timed_out and not vanished
    return fixed, regressions, still_failing, success


def feedback_for(attempt: Attempt) -> str:
    """Explain to the model why its previous attempt did not work."""
    lines = [f"## Previous attempt {attempt.number} did not work"]
    if attempt.diagnosis:
        lines.append(f"You proposed this for {attempt.diagnosis.file} :: {attempt.diagnosis.function}:")
        lines.append(f"```python\n{attempt.diagnosis.fixed_code}\n```")
    if attempt.error:
        lines.append(f"It was rejected before testing: {attempt.error}")
    if attempt.report:
        lines.append(f"Tests fixed by it: {attempt.fixed or 'none'}")
        lines.append(f"Tests it broke (regressions): {attempt.regressions or 'none'}")
        lines.append(f"Tests for this function that still fail: {attempt.still_failing or 'none'}")
        if attempt.report.timed_out:
            lines.append("The tests timed out (possible infinite loop).")
        lines.append(f"Test output after applying it:\n```\n{attempt.report.output.strip()}\n```")
    lines.append("Work out what was wrong with that attempt and propose a different fix.")
    return "\n".join(lines)


def run_fix(
    repo: str | Path,
    issue: str,
    llm: LLM | None = None,
    max_attempts: int = 3,
    approve: Approver | None = None,
    timeout: int = 60,
    on_event: Callable[[str], None] | None = None,
    include_tests: bool = True,
) -> FixResult:
    """Try to fix `issue` in `repo`. See the module docstring for the safety rules.

    approve: called with the winning patch. Return True to apply it to the real repo.
             None means never apply (a dry run).
    on_event: optional callback for progress messages (the CLI prints them).
    """
    say = on_event or (lambda msg: None)
    repo = Path(repo).resolve()
    llm = llm or LLM()
    start = time.perf_counter()
    result = FixResult(repo=str(repo), issue=issue)

    say("Running tests to get a baseline...")
    result.baseline = baseline = run_tests(repo, timeout=timeout)
    say(f"Baseline: {baseline.passed} passed, {baseline.failed} failed, {baseline.errors} errors")
    if not baseline.failed_tests:
        result.status = "nothing_to_fix"
        result.duration_s = round(time.perf_counter() - start, 3)
        return result

    scan = scan_repository(repo)
    feedback = None

    with tempfile.TemporaryDirectory() as tmp:
        for number in range(1, max_attempts + 1):
            attempt = Attempt(number=number)
            result.attempts.append(attempt)
            say(f"\nAttempt {number}/{max_attempts}: asking the model...")

            diag = diagnose(str(repo), issue, llm=llm, test_report=baseline, feedback=feedback, include_tests=include_tests)
            attempt.diagnosis = diag
            say(f"  Proposed change to {diag.file} :: {diag.function} (confidence {diag.confidence})")

            if diag.warnings:
                attempt.error = "; ".join(diag.warnings)
            else:
                try:
                    attempt.patch = make_patch(repo, scan, diag.file, diag.function, diag.fixed_code)
                except PatchError as exc:
                    attempt.error = str(exc)

            if attempt.error:
                say(f"  Rejected before testing: {attempt.error}")
                feedback = feedback_for(attempt)
                continue

            # Fresh sandbox copy for every attempt, so attempts never affect each other.
            sandbox = Path(tmp) / f"attempt{number}"
            shutil.copytree(repo, sandbox, ignore=SANDBOX_IGNORE)
            apply_patch(sandbox, attempt.patch)
            attempt.report = run_tests(sandbox, timeout=timeout)
            targets = related_tests(scan, baseline.failed_tests, diag.function)
            attempt.fixed, attempt.regressions, attempt.still_failing, attempt.success = compare_reports(
                baseline, attempt.report, targets
            )
            say(f"  Sandbox tests: {attempt.report.passed} passed, {attempt.report.failed} failed. "
                f"Fixed {len(attempt.fixed)}, still failing {len(attempt.still_failing)}, "
                f"regressions {len(attempt.regressions)}.")

            if attempt.success:
                break
            feedback = feedback_for(attempt)

    winner = result.winning_attempt
    if winner is None:
        result.status = "failed"
    elif approve is not None and approve(winner.patch, winner):
        apply_patch(repo, winner.patch)
        result.applied = True
        result.final_report = run_tests(repo, timeout=timeout)
        result.status = "fixed"
    else:
        result.status = "fixed_not_applied"

    result.duration_s = round(time.perf_counter() - start, 3)
    return result


def save_run(result: FixResult, runs_dir: str | Path = "runs", name: str | None = None) -> Path:
    """Write the full record of a run to runs/<time>-<issue>.json (or runs/<name>.json)."""
    runs_dir = Path(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    if name is None:
        slug = re.sub(r"[^a-z0-9]+", "-", result.issue.lower()).strip("-")[:40] or "issue"
        name = f"{datetime.now():%Y%m%d-%H%M%S}-{slug}"
    path = runs_dir / f"{name}.json"
    path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    return path