"""Tests for codefix.assistant. Using a fake LLM, so it cost nothing and need no API key."""

from pathlib import Path

from codefix.analyzer import scan_repository
from codefix.assistant import DIAGNOSIS_TOOL, Diagnosis, build_prompt, check_diagnosis, diagnose
from codefix.llm import Usage

SAMPLE_REPO = Path(__file__).resolve().parent.parent / "sample_repo"

GOOD_ANSWER = {
    "summary": "apply_discount returns the discount amount instead of the discounted total.",
    "file": "cart.py",
    "function": "apply_discount",
    "root_cause": "It multiplies by percent instead of (100 - percent).",
    "fixed_code": (
        "def apply_discount(total, percent):\n"
        '    """Return the total after a percentage discount. percent must be between 0 and 100."""\n'
        "    if percent < 0 or percent > 100:\n"
        '        raise ValueError("percent must be between 0 and 100")\n'
        "    return round(total * (100 - percent) / 100, 2)"
    ),
    "confidence": "high",
}


class FakeLLM:
    """Stands in for the real LLM. Records what it was sent and returns a fixed answer."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def call_tool(self, system, user, tool):
        self.calls.append({"system": system, "user": user, "tool": tool})
        return self.answer, Usage(model="fake", input_tokens=100, output_tokens=50, latency_s=0.0)


def make_diag(**changes) -> Diagnosis:
    return Diagnosis(**{**GOOD_ANSWER, **changes})


def test_prompt_contains_issue_and_relevant_source():
    scan = scan_repository(SAMPLE_REPO)
    prompt = build_prompt("Discount makes the price tiny", scan)
    assert "Discount makes the price tiny" in prompt
    assert "def apply_discount(total, percent):" in prompt
    assert "Output of the failing tests" not in prompt


def test_prompt_includes_test_output_when_given():
    scan = scan_repository(SAMPLE_REPO)
    prompt = build_prompt("Discount bug", scan, test_output="assert 20.0 == 180")
    assert "assert 20.0 == 180" in prompt


def test_prompt_falls_back_to_all_functions_when_search_finds_nothing():
    scan = scan_repository(SAMPLE_REPO)
    prompt = build_prompt("zebra quantum xylophone", scan)
    assert "def word_count(text):" in prompt
    assert "def apply_discount(total, percent):" in prompt


def test_good_diagnosis_has_no_warnings():
    assert check_diagnosis(make_diag(), scan_repository(SAMPLE_REPO)) == []


def test_unknown_function_is_flagged():
    warnings = check_diagnosis(make_diag(function="apply_coupon"), scan_repository(SAMPLE_REPO))
    assert any("not found" in w for w in warnings)


def test_code_that_does_not_parse_is_flagged():
    warnings = check_diagnosis(make_diag(fixed_code="def apply_discount(:"), scan_repository(SAMPLE_REPO))
    assert any("does not parse" in w for w in warnings)


def test_code_with_wrong_function_name_is_flagged():
    code = GOOD_ANSWER["fixed_code"].replace("def apply_discount", "def discount")
    warnings = check_diagnosis(make_diag(fixed_code=code), scan_repository(SAMPLE_REPO))
    assert any("exactly one function" in w for w in warnings)


def test_diagnose_end_to_end_with_fake_llm():
    fake = FakeLLM(GOOD_ANSWER)
    diag = diagnose(str(SAMPLE_REPO), "Discount makes the price tiny", llm=fake)

    assert diag.function == "apply_discount"
    assert diag.warnings == []
    assert diag.usage.input_tokens == 100
    sent = fake.calls[0]
    assert sent["tool"] is DIAGNOSIS_TOOL
    assert "assert 20.0 == 180" in sent["user"]