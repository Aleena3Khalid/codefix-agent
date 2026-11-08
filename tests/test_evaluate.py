"""Tests for the evaluation harness, using fake models (no API calls).

- OracleLLM answers every task with its reference fix: everything should be "correct".
- Trap answers pass the visible tests but not the hidden ones: they must be "incorrect".
"""

import json

import pytest

from codefix.bench_tasks import TASKS, get_task
from codefix.evaluate import CONFIGS, check_task, render_report, run_eval, summarize, write_results
from codefix.llm import Usage


def usage():
    return Usage(model="fake", input_tokens=1000, output_tokens=200, latency_s=0.0)


def reply(file, function, code):
    return {"summary": "s", "file": file, "function": function, "root_cause": "r",
            "fixed_code": code, "confidence": "high"}


class OracleLLM:
    """Finds which task the prompt is about and returns that task's reference fix."""

    def call_tool(self, system, user, tool):
        task = next(t for t in TASKS if t.issue in user)
        return reply(task.fix_file, task.fix_function, task.fix_code), usage()


class FixedLLM:
    """Always returns the same answer."""

    def __init__(self, answer):
        self.answer = answer

    def call_tool(self, system, user, tool):
        return self.answer, usage()


class BrokenLLM:
    def call_tool(self, system, user, tool):
        raise ConnectionError("network down")


@pytest.mark.parametrize("task", TASKS, ids=[t.id for t in TASKS])
def test_every_task_is_valid(task):
    assert check_task(task) == []


def test_task_ids_are_unique():
    ids = [t.id for t in TASKS]
    assert len(ids) == len(set(ids))


def test_oracle_gets_everything_correct():
    tasks = [get_task(i) for i in ("average_empty", "withdraw_full_balance", "running_total_vague", "price_helper")]
    rows = run_eval(tasks, [CONFIGS["single"]], OracleLLM())
    assert [r.outcome for r in rows] == ["correct"] * 4
    assert all(r.hidden_failed == 0 and r.hidden_passed > 0 for r in rows)


LEAP_TRAP = '''def is_leap_year(year):
    """Gregorian calendar leap year rule."""
    return (year % 4 == 0 and year % 100 != 0) or year == 2000
'''

MEDIAN_TRAP = '''def median(values):
    """Return the median of a list of numbers. The input list is not modified."""
    values.sort()
    mid = len(values) // 2
    if len(values) % 2 == 0:
        return (values[mid - 1] + values[mid]) / 2
    return values[mid]
'''

PRICE_TRAP = '''def order_total(price_texts):
    """Add up a list of prices like "£1,234.50"."""
    return round(sum(float(t.replace("£", "").replace(",", "")) for t in price_texts), 2)
'''


@pytest.mark.parametrize("task_id, answer", [
    ("leap_year", reply("dates.py", "is_leap_year", LEAP_TRAP)),
    ("median_two_bugs", reply("median.py", "median", MEDIAN_TRAP)),
    ("price_helper", reply("prices.py", "order_total", PRICE_TRAP)),
])
def test_fixes_that_only_fool_the_visible_tests_are_incorrect(task_id, answer):
    [row] = run_eval([get_task(task_id)], [CONFIGS["single"]], FixedLLM(answer))
    assert row.outcome == "incorrect"
    assert row.hidden_failed > 0


def test_wrong_fix_is_failed():
    wrong = reply("limits.py", "clamp", 'def clamp(value, low, high):\n    return value\n')
    [row] = run_eval([get_task("clamp_order")], [CONFIGS["agent"]], FixedLLM(wrong))
    assert row.outcome == "failed"
    assert row.attempts == 3


def test_api_error_is_recorded_not_raised():
    [row] = run_eval([get_task("clamp_order")], [CONFIGS["single"]], BrokenLLM())
    assert row.outcome == "error"
    assert "network down" in row.error


def test_summary_report_and_files(tmp_path):
    tasks = [get_task("average_empty"), get_task("leap_year")]
    rows = run_eval(tasks, [CONFIGS["single"], CONFIGS["agent"]], OracleLLM(), runs_dir=tmp_path / "runs")

    summary = summarize(rows)
    assert summary["single"]["correct"] == 2
    assert summary["agent"]["mean_attempts"] == 1
    assert summary["single"]["cost_per_correct_usd"] is None   # fake model has no price

    meta = {"date": "d", "model": "fake", "commit": "abc", "tasks": 2, "repeats": 1, "configs": {}}
    report_path = write_results(rows, meta, tmp_path / "out")
    report = report_path.read_text(encoding="utf-8")
    assert "| Correct | 2/2 (100%) | 2/2 (100%) |" in report
    assert json.loads((tmp_path / "out" / "results.json").read_text())["summary"]["agent"]["runs"] == 2
    assert len((tmp_path / "out" / "results.csv").read_text().strip().splitlines()) == 5  # header + 4 rows
    assert len(list((tmp_path / "runs").glob("*.json"))) == 4
    assert render_report(rows, meta).startswith("# CodeFix Agent evaluation")