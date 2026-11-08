"""Run the benchmark and write a report.

For every task and every configuration:
1. Build the task's repo in a temporary folder.
2. Run the agent on it (approval is automatic: it is a throwaway copy).
3. If a fix was applied, add the hidden tests and run them.
4. Classify the outcome:
   correct    the agent's fix passed the visible checks AND the hidden tests
   incorrect  it passed the visible checks but failed the hidden tests (a wrong fix)
   failed     no attempt passed the visible checks
5. Record attempts, tokens, cost and time.

Results are written to eval_results/<timestamp>/: results.json, results.csv,
report.md, and one full run log per task in runs/.
"""

from __future__ import annotations

import csv
import json
import statistics
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from codefix.agent import run_fix, save_run
from codefix.analyzer import scan_repository
from codefix.bench_tasks import TASKS, Task
from codefix.patcher import PatchError, apply_patch, make_patch
from codefix.test_runner import run_tests

PYTEST_INI = "[pytest]\npythonpath = .\n"
HIDDEN_PATH = "tests/test_hidden.py"


@dataclass
class Config:
    """One way of running the agent. Comparing configs is the point of the evaluation."""

    name: str
    max_attempts: int
    include_tests: bool = True
    description: str = ""


CONFIGS = {
    "single": Config("single", max_attempts=1, description="Baseline: one LLM call, no repair loop."),
    "agent": Config("agent", max_attempts=3, description="Full agent: up to 3 attempts with test feedback."),
    "no-tests": Config("no-tests", max_attempts=1, include_tests=False,
                       description="One LLM call without the failing test output in the prompt."),
}


@dataclass
class Row:
    task: str
    difficulty: str
    config: str
    repeat: int
    outcome: str            # correct | incorrect | failed | error
    attempts: int
    attempts_with_regressions: int
    hidden_passed: int
    hidden_failed: int
    llm_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    duration_s: float
    error: str = ""


def materialize(task: Task, dest: Path, with_hidden: bool = False) -> Path:
    """Write a task's repo files into `dest` and return it."""
    dest.mkdir(parents=True, exist_ok=True)
    files = dict(task.files)
    files.setdefault("pytest.ini", PYTEST_INI)
    if with_hidden:
        files[HIDDEN_PATH] = task.hidden_tests
    for rel, content in files.items():
        path = dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))
    return dest


def check_task(task: Task) -> list[str]:
    """Check that a task is a fair test. Returns a list of problems (empty means valid).

    - the bug is real: at least one visible test fails,
    - the reference fix works: it passes every visible and hidden test.
    """
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        repo = materialize(task, Path(tmp) / "repo")
        before = run_tests(repo)
        if before.timed_out:
            problems.append("visible tests time out on the buggy code")
        if not before.failed_tests:
            problems.append("no visible test fails on the buggy code")

        try:
            patch = make_patch(repo, scan_repository(repo), task.fix_file, task.fix_function, task.fix_code)
            apply_patch(repo, patch)
        except PatchError as exc:
            problems.append(f"reference fix cannot be applied: {exc}")
            return problems

        (repo / HIDDEN_PATH).write_bytes(task.hidden_tests.encode("utf-8"))
        after = run_tests(repo)
        if not after.all_passed:
            problems.append(f"reference fix does not pass all tests: {after.failed_tests}")
    return problems


def run_one(task: Task, config: Config, llm, repeat: int, runs_dir: Path | None, timeout: int = 60) -> Row:
    with tempfile.TemporaryDirectory() as tmp:
        repo = materialize(task, Path(tmp) / "repo")
        try:
            result = run_fix(
                repo, task.issue, llm=llm,
                max_attempts=config.max_attempts,
                include_tests=config.include_tests,
                approve=lambda patch, attempt: True,   # safe: this repo is a throwaway copy
                timeout=timeout,
            )
        except Exception as exc:  # an API error must not stop the whole benchmark
            return Row(task.id, task.difficulty, config.name, repeat, "error", 0, 0, 0, 0, 0, 0, 0, None, 0.0,
                       error=f"{type(exc).__name__}: {exc}")

        hidden_passed = hidden_failed = 0
        if result.applied:
            (repo / HIDDEN_PATH).write_bytes(task.hidden_tests.encode("utf-8"))
            hidden = run_tests(repo, target=HIDDEN_PATH, timeout=timeout)
            hidden_passed = hidden.passed
            hidden_failed = hidden.failed + hidden.errors + (1 if hidden.timed_out else 0)
            outcome = "correct" if hidden_failed == 0 and hidden_passed > 0 else "incorrect"
        else:
            outcome = "failed"

        if runs_dir is not None:
            save_run(result, runs_dir, name=f"{task.id}-{config.name}-{repeat}")

        totals = result.totals()
        return Row(
            task=task.id,
            difficulty=task.difficulty,
            config=config.name,
            repeat=repeat,
            outcome=outcome,
            attempts=len(result.attempts),
            attempts_with_regressions=sum(1 for a in result.attempts if a.regressions),
            hidden_passed=hidden_passed,
            hidden_failed=hidden_failed,
            llm_calls=totals["llm_calls"],
            input_tokens=totals["input_tokens"],
            output_tokens=totals["output_tokens"],
            cost_usd=totals["cost_usd"],
            duration_s=result.duration_s,
        )


def run_eval(
    tasks: list[Task],
    configs: list[Config],
    llm,
    repeats: int = 1,
    runs_dir: Path | None = None,
    on_event: Callable[[str], None] | None = None,
) -> list[Row]:
    say = on_event or (lambda msg: None)
    rows = []
    total = len(tasks) * len(configs) * repeats
    n = 0
    for repeat in range(1, repeats + 1):
        for task in tasks:
            for config in configs:
                n += 1
                row = run_one(task, config, llm, repeat, runs_dir)
                rows.append(row)
                cost = f"${row.cost_usd:.4f}" if row.cost_usd is not None else "?"
                say(f"[{n}/{total}] {task.id:<22} {config.name:<9} {row.outcome:<9} "
                    f"attempts={row.attempts} {cost} {row.duration_s}s")
    return rows


# ---------------------------------------------------------------- summaries

def summarize(rows: list[Row]) -> dict[str, dict]:
    """Aggregate metrics per config."""
    out = {}
    for config in dict.fromkeys(r.config for r in rows):
        rs = [r for r in rows if r.config == config]
        n = len(rs)
        correct = sum(r.outcome == "correct" for r in rs)
        costs = [r.cost_usd for r in rs]
        total_cost = None if None in costs else round(sum(costs), 4)
        out[config] = {
            "runs": n,
            "correct": correct,
            "incorrect": sum(r.outcome == "incorrect" for r in rs),
            "failed": sum(r.outcome == "failed" for r in rs),
            "errors": sum(r.outcome == "error" for r in rs),
            "correct_rate": round(correct / n, 3) if n else 0.0,
            "mean_attempts": round(statistics.mean(r.attempts for r in rs), 2) if n else 0.0,
            "attempts_with_regressions": sum(r.attempts_with_regressions for r in rs),
            "mean_duration_s": round(statistics.mean(r.duration_s for r in rs), 2) if n else 0.0,
            "total_tokens": sum(r.input_tokens + r.output_tokens for r in rs),
            "total_cost_usd": total_cost,
            "cost_per_correct_usd": round(total_cost / correct, 4) if total_cost is not None and correct else None,
        }
    return out


def by_difficulty(rows: list[Row]) -> dict[str, dict[str, str]]:
    """correct/total per difficulty per config, e.g. {'easy': {'single': '4/5'}}."""
    table: dict[str, dict[str, str]] = {}
    for difficulty in ("easy", "medium", "hard"):
        for config in dict.fromkeys(r.config for r in rows):
            rs = [r for r in rows if r.difficulty == difficulty and r.config == config]
            if rs:
                ok = sum(r.outcome == "correct" for r in rs)
                table.setdefault(difficulty, {})[config] = f"{ok}/{len(rs)}"
    return table


def git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def render_report(rows: list[Row], meta: dict) -> str:
    summary = summarize(rows)
    configs = list(summary)
    money = lambda v: f"${v:.4f}" if v is not None else "n/a"

    lines = [
        "# CodeFix Agent evaluation",
        "",
        f"- Date: {meta['date']}",
        f"- Model: {meta['model']}",
        f"- Code version (git): {meta['commit']}",
        f"- Tasks: {meta['tasks']} | Repeats: {meta['repeats']}",
        "",
        "Outcomes: **correct** = passed the visible checks and the hidden tests; "
        "**incorrect** = passed the visible checks but failed hidden tests (a wrong fix that looked right); "
        "**failed** = no attempt passed the visible checks.",
        "",
        "## Summary",
        "",
        "| Metric | " + " | ".join(configs) + " |",
        "|---|" + "---|" * len(configs),
    ]
    metrics = [
        ("Correct", lambda s: f"{s['correct']}/{s['runs']} ({s['correct_rate']:.0%})"),
        ("Incorrect fixes", lambda s: str(s["incorrect"])),
        ("Failed", lambda s: str(s["failed"])),
        ("API errors", lambda s: str(s["errors"])),
        ("Mean attempts", lambda s: str(s["mean_attempts"])),
        ("Attempts that caused regressions (caught)", lambda s: str(s["attempts_with_regressions"])),
        ("Mean time per task", lambda s: f"{s['mean_duration_s']}s"),
        ("Total tokens", lambda s: f"{s['total_tokens']:,}"),
        ("Total cost", lambda s: money(s["total_cost_usd"])),
        ("Cost per correct fix", lambda s: money(s["cost_per_correct_usd"])),
    ]
    for label, fmt in metrics:
        lines.append(f"| {label} | " + " | ".join(fmt(summary[c]) for c in configs) + " |")

    lines += ["", "## Correct fixes by difficulty", "", "| Difficulty | " + " | ".join(configs) + " |",
              "|---|" + "---|" * len(configs)]
    for difficulty, cells in by_difficulty(rows).items():
        lines.append(f"| {difficulty} | " + " | ".join(cells.get(c, "-") for c in configs) + " |")

    lines += ["", "## Per task", "", "| Task | Difficulty | " + " | ".join(configs) + " |",
              "|---|---|" + "---|" * len(configs)]
    for task_id in dict.fromkeys(r.task for r in rows):
        rs = [r for r in rows if r.task == task_id]
        cells = []
        for c in configs:
            outcomes = [r for r in rs if r.config == c]
            cells.append(", ".join(f"{r.outcome} ({r.attempts})" for r in outcomes) or "-")
        lines.append(f"| {task_id} | {rs[0].difficulty} | " + " | ".join(cells) + " |")
    lines += ["", "Numbers in brackets are attempts used.", ""]
    return "\n".join(lines)


def write_results(rows: list[Row], meta: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    data = {"meta": meta, "summary": summarize(rows), "rows": [asdict(r) for r in rows]}
    (out_dir / "results.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    with open(out_dir / "results.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()))
        writer.writeheader()
        writer.writerows(asdict(r) for r in rows)
    report = out_dir / "report.md"
    report.write_text(render_report(rows, meta), encoding="utf-8")
    return report


def new_results_dir(base: str | Path = "eval_results") -> Path:
    return Path(base) / datetime.now().strftime("%Y%m%d-%H%M%S")


def select_tasks(ids: str | None) -> list[Task]:
    if not ids:
        return list(TASKS)
    wanted = [i.strip() for i in ids.split(",") if i.strip()]
    known = {t.id: t for t in TASKS}
    missing = [i for i in wanted if i not in known]
    if missing:
        raise SystemExit(f"Unknown task id(s): {', '.join(missing)}")
    return [known[i] for i in wanted]