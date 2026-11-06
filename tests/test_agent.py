"""Tests for the repair loop, using a fake LLM that returns a scripted list of answers.

Every test copies sample_repo into tmp_path first, because the agent may change files.
"""

import json
import shutil
from pathlib import Path

import pytest

from codefix.agent import run_fix, save_run
from codefix.llm import Usage
from codefix.test_runner import run_tests

SAMPLE_REPO = Path(__file__).resolve().parent.parent / "sample_repo"

HEADER = (
    "def apply_discount(total, percent):\n"
    '    """Return the total after a percentage discount. percent must be between 0 and 100."""\n'
)
CHECK = (
    "    if percent < 0 or percent > 100:\n"
    '        raise ValueError("percent must be between 0 and 100")\n'
)


def answer(body: str, function="apply_discount", file="cart.py") -> dict:
    return {
        "summary": "s", "file": file, "function": function, "root_cause": "r",
        "fixed_code": body, "confidence": "high",
    }


RIGHT = answer(HEADER + CHECK + "    return round(total * (100 - percent) / 100, 2)")
WRONG = answer(HEADER + CHECK + "    return round(total - percent, 2)")            # 200 - 10 = 190
REGRESSES = answer(HEADER + "    return round(total * (100 - percent) / 100, 2)")  # drops the ValueError check
UNKNOWN = answer(HEADER + CHECK + "    return 0", function="apply_coupon")


class ScriptedLLM:
    """Returns the given answers in order and records every prompt it receives."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def call_tool(self, system, user, tool):
        self.prompts.append(user)
        return self.answers.pop(0), Usage(model="fake", input_tokens=1000, output_tokens=200, latency_s=0.0)


@pytest.fixture
def repo(tmp_path):
    copy = tmp_path / "repo"
    shutil.copytree(SAMPLE_REPO, copy)
    return copy


def yes(patch, attempt):
    return True


def no(patch, attempt):
    return False


def test_fixes_on_first_attempt_and_applies(repo):
    result = run_fix(repo, "Discount makes the price tiny", llm=ScriptedLLM(RIGHT), approve=yes)

    assert result.status == "fixed"
    assert result.applied
    assert len(result.attempts) == 1
    assert result.attempts[0].fixed == [
        "tests/test_cart.py::test_apply_discount",
        "tests/test_cart.py::test_apply_discount_zero",
    ]
    assert "(100 - percent)" in (repo / "cart.py").read_text()
    assert (result.final_report.passed, result.final_report.failed) == (10, 2)


def test_retries_after_a_wrong_fix_and_sends_feedback(repo):
    llm = ScriptedLLM(WRONG, RIGHT)
    result = run_fix(repo, "Discount makes the price tiny", llm=llm, approve=yes)

    assert result.status == "fixed"
    assert [a.success for a in result.attempts] == [False, True]
    second_prompt = llm.prompts[1]
    assert "Previous attempt 1 did not work" in second_prompt
    assert "total - percent" in second_prompt   # the failed code was shown back
    assert "190" in second_prompt               # and the new test failure


def test_partial_fix_is_not_a_success(repo):
    """WRONG passes test_apply_discount_zero (99.99 - 0) but not test_apply_discount (190 != 180)."""
    result = run_fix(repo, "Discount bug", llm=ScriptedLLM(WRONG), max_attempts=1, approve=yes)
    attempt = result.attempts[0]
    assert attempt.fixed == ["tests/test_cart.py::test_apply_discount_zero"]
    assert attempt.still_failing == ["tests/test_cart.py::test_apply_discount"]
    assert result.status == "failed"


def test_regression_is_not_a_success(repo):
    result = run_fix(repo, "Discount bug", llm=ScriptedLLM(REGRESSES), max_attempts=1, approve=yes)

    attempt = result.attempts[0]
    assert attempt.fixed  # it did fix the two discount tests...
    assert attempt.regressions == ["tests/test_cart.py::test_apply_discount_rejects_bad_percent"]
    assert result.status == "failed"   # ...but broke another one, so it is rejected
    assert not result.applied


def test_invalid_answer_is_rejected_before_testing(repo):
    llm = ScriptedLLM(UNKNOWN, RIGHT)
    result = run_fix(repo, "Discount bug", llm=llm, approve=yes)

    assert result.attempts[0].error and "not found" in result.attempts[0].error
    assert result.attempts[0].report is None   # never tested
    assert result.status == "fixed"


def test_gives_up_after_max_attempts_and_leaves_repo_alone(repo):
    before = (repo / "cart.py").read_text()
    result = run_fix(repo, "Discount bug", llm=ScriptedLLM(WRONG, WRONG), max_attempts=2, approve=yes)

    assert result.status == "failed"
    assert len(result.attempts) == 2
    assert (repo / "cart.py").read_text() == before


def test_declined_approval_leaves_repo_alone(repo):
    before = (repo / "cart.py").read_text()
    result = run_fix(repo, "Discount bug", llm=ScriptedLLM(RIGHT), approve=no)

    assert result.status == "fixed_not_applied"
    assert (repo / "cart.py").read_text() == before


def test_sandbox_attempts_never_touch_the_real_repo(repo):
    before = (repo / "cart.py").read_text()
    run_fix(repo, "Discount bug", llm=ScriptedLLM(WRONG, RIGHT), approve=None)  # dry run
    assert (repo / "cart.py").read_text() == before
    assert run_tests(repo).failed == 4


def test_nothing_to_fix_when_all_tests_pass(tmp_path):
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    llm = ScriptedLLM()
    result = run_fix(tmp_path, "anything", llm=llm, approve=yes)
    assert result.status == "nothing_to_fix"
    assert llm.prompts == []   # no money spent


def test_totals_and_log(repo, tmp_path):
    result = run_fix(repo, "Discount makes the price tiny!", llm=ScriptedLLM(WRONG, RIGHT), approve=yes)
    assert result.totals()["llm_calls"] == 2
    assert result.totals()["input_tokens"] == 2000

    path = save_run(result, tmp_path / "runs")
    data = json.loads(path.read_text())
    assert path.name.endswith("discount-makes-the-price-tiny.json")
    assert data["status"] == "fixed"
    assert len(data["attempts"]) == 2
    assert "+    return round(total * (100 - percent) / 100, 2)" in data["attempts"][1]["patch"]["diff"]