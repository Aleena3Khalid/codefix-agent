"""Tests for codefix.test_runner. These start real pytest subprocesses."""

from pathlib import Path

from codefix.test_runner import run_tests

SAMPLE_REPO = Path(__file__).resolve().parent.parent / "sample_repo"


def make_repo(root: Path, test_code: str) -> Path:
    (root / "tests").mkdir()
    (root / "tests" / "test_example.py").write_text(test_code)
    return root


def test_counts_passes_and_failures(tmp_path):
    repo = make_repo(tmp_path, (
        "import pytest\n"
        "def test_ok():\n    assert 1 + 1 == 2\n"
        "def test_bad():\n    assert 1 + 1 == 3\n"
        "@pytest.mark.skip\ndef test_skipped():\n    pass\n"
    ))
    report = run_tests(repo)

    assert (report.passed, report.failed, report.skipped) == (1, 1, 1)
    assert report.failed_tests == ["tests/test_example.py::test_bad"]
    assert report.pass_rate == 0.5
    assert report.all_passed is False
    assert report.exit_code == 1


def test_all_passing(tmp_path):
    repo = make_repo(tmp_path, "def test_ok():\n    assert True\n")
    report = run_tests(repo)
    assert report.all_passed and report.exit_code == 0


def test_tests_inside_a_class_get_full_id(tmp_path):
    repo = make_repo(tmp_path, "class TestMath:\n    def test_fail(self):\n        assert False\n")
    assert run_tests(repo).failed_tests == ["tests/test_example.py::TestMath::test_fail"]


def test_import_error_counts_as_error(tmp_path):
    repo = make_repo(tmp_path, "import does_not_exist\n\ndef test_x():\n    pass\n")
    report = run_tests(repo)
    assert report.errors >= 1
    assert report.all_passed is False


def test_timeout_stops_slow_tests(tmp_path):
    repo = make_repo(tmp_path, "import time\ndef test_slow():\n    time.sleep(30)\n")
    report = run_tests(repo, timeout=2)
    assert report.timed_out is True
    assert report.all_passed is False


def test_single_test_target(tmp_path):
    repo = make_repo(tmp_path, "def test_a():\n    pass\ndef test_b():\n    assert False\n")
    report = run_tests(repo, target="tests/test_example.py::test_a")
    assert (report.passed, report.failed) == (1, 0)


def test_sample_repo_has_the_known_bugs():
    """The sample repo ships with 3 bugs that break exactly 4 tests."""
    report = run_tests(SAMPLE_REPO)
    assert sorted(report.failed_tests) == [
        "tests/test_cart.py::test_apply_discount",
        "tests/test_cart.py::test_apply_discount_zero",
        "tests/test_cart.py::test_free_shipping_at_threshold",
        "tests/test_text_utils.py::test_word_count_extra_spaces",
    ]
    assert report.passed == 8