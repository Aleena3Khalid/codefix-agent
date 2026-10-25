"""Tests for codefix.analyzer.

`tmp_path` is a pytest fixture: a fresh empty folder for each test, deleted
afterwards. We write tiny fake repos into it so each test controls its input.
"""

from pathlib import Path

from codefix.analyzer import get_function_source, scan_repository, search_functions

SAMPLE_REPO = Path(__file__).resolve().parent.parent / "sample_repo"


def write(root: Path, rel: str, code: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code)


def test_finds_functions_and_methods(tmp_path):
    write(tmp_path, "shop.py", (
        "def total(items, *, tax=0):\n"
        "    '''Add up items.'''\n"
        "    return sum(items)\n"
        "\n"
        "class Basket:\n"
        "    def add(self, item):\n"
        "        pass\n"
    ))
    result = scan_repository(tmp_path)
    names = {f.qualified_name: f for f in result.functions}

    assert set(names) == {"total", "Basket.add"}
    assert names["total"].args == ["items", "tax"]
    assert names["total"].docstring == "Add up items."
    assert (names["total"].start_line, names["total"].end_line) == (1, 3)
    assert names["Basket.add"].class_name == "Basket"


def test_async_functions_are_found(tmp_path):
    write(tmp_path, "net.py", "async def fetch(url):\n    return url\n")
    assert [f.name for f in scan_repository(tmp_path).functions] == ["fetch"]


def test_syntax_error_is_recorded_not_raised(tmp_path):
    write(tmp_path, "good.py", "def ok():\n    pass\n")
    write(tmp_path, "bad.py", "def broken(:\n")
    result = scan_repository(tmp_path)

    assert [f.name for f in result.functions] == ["ok"]
    assert "bad.py" in result.errors


def test_skips_virtualenv_and_cache_folders(tmp_path):
    write(tmp_path, "app.py", "def main():\n    pass\n")
    write(tmp_path, ".venv/lib/thing.py", "def hidden():\n    pass\n")
    write(tmp_path, "__pycache__/x.py", "def hidden2():\n    pass\n")
    assert scan_repository(tmp_path).files == ["app.py"]


def test_separates_tests_from_source(tmp_path):
    write(tmp_path, "calc.py", "def add(a, b):\n    return a + b\n")
    write(tmp_path, "tests/test_calc.py", "def test_add():\n    assert True\n")
    result = scan_repository(tmp_path)

    assert [f.name for f in result.source_functions()] == ["add"]
    assert [f.name for f in result.test_functions()] == ["test_add"]


def test_get_function_source(tmp_path):
    write(tmp_path, "m.py", "x = 1\n\ndef double(n):\n    return n * 2\n")
    result = scan_repository(tmp_path)
    assert get_function_source(tmp_path, result.functions[0]) == "def double(n):\n    return n * 2"


def test_search_ranks_name_matches_first():
    result = scan_repository(SAMPLE_REPO)
    matches = search_functions(result, "Applying a discount gives the wrong price")
    assert matches[0][0].name == "apply_discount"


def test_search_handles_snake_case_query():
    result = scan_repository(SAMPLE_REPO)
    matches = search_functions(result, "word_count is too high")
    assert matches[0][0].name == "word_count"


def test_search_returns_empty_for_unrelated_query():
    result = scan_repository(SAMPLE_REPO)
    assert search_functions(result, "zebra quantum xylophone") == []