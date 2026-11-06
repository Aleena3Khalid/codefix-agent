"""Turn a proposed function into a reviewable patch, and apply it safely.

A patch here is: which file, the full original text, and the full new text.
From those two texts we can show a unified diff (the same format as `git diff`)
for a human to review, and apply or undo the change exactly.
"""

from __future__ import annotations

import ast
import difflib
import textwrap
from dataclasses import dataclass
from pathlib import Path

from codefix.analyzer import ScanResult


class PatchError(ValueError):
    """The proposed change cannot be turned into a valid patch."""


@dataclass
class Patch:
    file: str       # path relative to the repo root, e.g. "cart.py"
    function: str   # qualified name, e.g. "apply_discount" or "Cart.add"
    original: str   # full file text before the change
    patched: str    # full file text after the change

    def diff(self) -> str:
        """Unified diff, as `git diff` would show it."""
        return "".join(
            difflib.unified_diff(
                self.original.splitlines(keepends=True),
                self.patched.splitlines(keepends=True),
                fromfile=f"a/{self.file}",
                tofile=f"b/{self.file}",
            )
        )

    def to_dict(self) -> dict:
        return {"file": self.file, "function": self.function, "diff": self.diff()}


def read_source(path: Path) -> str:
    # newline="" keeps \r\n line endings exactly as they are in the file (Windows files).
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def write_source(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def make_patch(root: str | Path, scan: ScanResult, file: str, function: str, new_code: str) -> Patch:
    """Replace one function in one file with `new_code` and return the result as a Patch.

    Nothing is written to disk here.
    """
    matches = [f for f in scan.source_functions() if f.file == file and f.qualified_name == function]
    if not matches:
        raise PatchError(f"Function {function!r} not found in {file!r}.")
    func = matches[0]

    original = read_source(Path(root) / file)
    eol = "\r\n" if "\r\n" in original else "\n"
    lines = original.splitlines(keepends=True)

    # Re-indent the new code to match the original def line. A method inside a class
    # is indented, but the model usually returns the function starting at column 0.
    def_line = lines[func.start_line - 1]
    indent = def_line[: len(def_line) - len(def_line.lstrip())]
    body = textwrap.dedent(new_code).strip("\n")
    new_lines = [(indent + line if line.strip() else "") for line in body.splitlines()]
    new_block = eol.join(new_lines) + eol

    patched = "".join(lines[: func.start_line - 1]) + new_block + "".join(lines[func.end_line :])

    if patched == original:
        raise PatchError("The proposed code is identical to the current code.")
    try:
        ast.parse(patched)
    except SyntaxError as exc:
        raise PatchError(f"The patched file would not parse: {exc}") from exc

    return Patch(file=file, function=function, original=original, patched=patched)


def apply_patch(root: str | Path, patch: Patch) -> None:
    """Write the patched text, but only if the file still matches what the patch was made from."""
    path = Path(root) / patch.file
    if read_source(path) != patch.original:
        raise PatchError(f"{patch.file} has changed since the patch was made. Not applying it.")
    write_source(path, patch.patched)


def revert_patch(root: str | Path, patch: Patch) -> None:
    """Put the original text back."""
    write_source(Path(root) / patch.file, patch.original)