"""Tests for the command-line interface. `capsys` captures what gets printed."""

import json
from pathlib import Path

from codefix.cli import main

SAMPLE = str(Path(__file__).resolve().parent.parent / "sample_repo")


def test_scan_lists_functions(capsys):
    assert main(["scan", SAMPLE]) == 0
    out = capsys.readouterr().out
    assert "apply_discount(total, percent)" in out
    assert "Cart.add(self, name, price, qty)" in out


def test_scan_json_is_valid(capsys):
    main(["scan", SAMPLE, "--json"])
    data = json.loads(capsys.readouterr().out)
    assert "cart.py" in data["files"]


def test_find(capsys):
    assert main(["find", SAMPLE, "free shipping threshold"]) == 0
    assert "qualifies_for_free_shipping" in capsys.readouterr().out.splitlines()[0]


def test_show(capsys):
    assert main(["show", SAMPLE, "word_count"]) == 0
    assert "def word_count(text):" in capsys.readouterr().out


def test_test_command_reports_failures(capsys):
    assert main(["test", SAMPLE]) == 1  # sample repo has known bugs
    out = capsys.readouterr().out
    assert out.startswith("FAIL: 8 passed, 4 failed")