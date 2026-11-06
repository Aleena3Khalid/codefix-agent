"""Tests for codefix.patcher. Each test works on its own copy of a small file in tmp_path."""

import pytest

from codefix.analyzer import scan_repository
from codefix.patcher import PatchError, apply_patch, make_patch, read_source, revert_patch

CODE = (
    "def add(a, b):\n"
    "    return a - b\n"
    "\n"
    "\n"
    "class Box:\n"
    "    def size(self):\n"
    "        return 0\n"
    "\n"
    "\n"
    "def untouched():\n"
    "    return 'same'\n"
)
FIXED_ADD = "def add(a, b):\n    return a + b"


@pytest.fixture
def repo(tmp_path):
    # write_bytes, not write_text: on Windows write_text turns every \n into \r\n,
    # and these tests need the file to contain exactly CODE.
    (tmp_path / "m.py").write_bytes(CODE.encode())
    return tmp_path


def test_replaces_only_the_target_function(repo):
    patch = make_patch(repo, scan_repository(repo), "m.py", "add", FIXED_ADD)
    assert patch.patched == CODE.replace("return a - b", "return a + b")
    assert "-    return a - b" in patch.diff()
    assert "+    return a + b" in patch.diff()


def test_method_is_reindented_inside_its_class(repo):
    new = "def size(self):\n    return 42"  # model returns it at column 0
    patch = make_patch(repo, scan_repository(repo), "m.py", "Box.size", new)
    assert "    def size(self):\n        return 42\n" in patch.patched


def test_unknown_function_raises(repo):
    with pytest.raises(PatchError, match="not found"):
        make_patch(repo, scan_repository(repo), "m.py", "subtract", FIXED_ADD)


def test_code_that_breaks_the_file_raises(repo):
    with pytest.raises(PatchError, match="would not parse"):
        make_patch(repo, scan_repository(repo), "m.py", "add", "def add(a, b):\n    return (a +")


def test_identical_code_raises(repo):
    with pytest.raises(PatchError, match="identical"):
        make_patch(repo, scan_repository(repo), "m.py", "add", "def add(a, b):\n    return a - b")


def test_make_patch_does_not_write_to_disk(repo):
    make_patch(repo, scan_repository(repo), "m.py", "add", FIXED_ADD)
    assert (repo / "m.py").read_text() == CODE


def test_apply_and_revert(repo):
    patch = make_patch(repo, scan_repository(repo), "m.py", "add", FIXED_ADD)
    apply_patch(repo, patch)
    assert "return a + b" in (repo / "m.py").read_text()
    revert_patch(repo, patch)
    assert (repo / "m.py").read_text() == CODE


def test_apply_refuses_if_file_changed_meanwhile(repo):
    patch = make_patch(repo, scan_repository(repo), "m.py", "add", FIXED_ADD)
    (repo / "m.py").write_text(CODE + "\n# edited by someone else\n")
    with pytest.raises(PatchError, match="has changed"):
        apply_patch(repo, patch)


def test_windows_line_endings_are_kept(tmp_path):
    (tmp_path / "w.py").write_bytes(CODE.replace("\n", "\r\n").encode())
    patch = make_patch(tmp_path, scan_repository(tmp_path), "w.py", "add", FIXED_ADD)
    apply_patch(tmp_path, patch)
    text = read_source(tmp_path / "w.py")
    assert "return a + b\r\n" in text
    assert "\n" not in text.replace("\r\n", "")