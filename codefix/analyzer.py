"""Scan a Python repository and describe the functions inside it."""

from __future__ import annotations

import ast
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Folders we never want to scan.
SKIP_DIRS = {".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache", "node_modules", "build", "dist"}


def find_python_files(root: Path) -> list[Path]:
    """Return all .py files under `root`, sorted, skipping SKIP_DIRS."""
    root = Path(root)
    found = []
    for path in sorted(root.rglob("*.py")):
        relative_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in relative_parts):
            continue
        found.append(path)
    return found


@dataclass
class FunctionInfo:
    """Everything we know about one function or method."""

    name: str
    file: str  # path relative to the repo root, e.g. "cart.py"
    start_line: int
    end_line: int
    args: list[str]
    docstring: str | None = None
    class_name: str | None = None  # set when the function is a method

    @property
    def qualified_name(self) -> str:
        """`Cart.add` for methods, `apply_discount` for plain functions."""
        return f"{self.class_name}.{self.name}" if self.class_name else self.name

    @property
    def is_test(self) -> bool:
        return self.name.startswith("test_") or Path(self.file).name.startswith("test_")

    def to_dict(self) -> dict:
        data = asdict(self)
        data["qualified_name"] = self.qualified_name
        return data


@dataclass
class ScanResult:
    """The output of scanning a whole repository."""

    root: str
    files: list[str] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)  # file -> parse error message

    def source_functions(self) -> list[FunctionInfo]:
        """Functions that are not tests."""
        return [f for f in self.functions if not f.is_test]

    def test_functions(self) -> list[FunctionInfo]:
        return [f for f in self.functions if f.is_test]

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "files": self.files,
            "functions": [f.to_dict() for f in self.functions],
            "errors": self.errors,
        }


class _FunctionVisitor(ast.NodeVisitor):
    """Walks an AST and collects functions, remembering which class each one is in."""

    def __init__(self, rel_path: str):
        self.rel_path = rel_path
        self.functions: list[FunctionInfo] = []
        self._class_stack: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_stack.append(node.name)
        self.generic_visit(node)  # keep walking into the class body
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.functions.append(
            FunctionInfo(
                name=node.name,
                file=self.rel_path,
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
                args=_argument_names(node.args),
                docstring=ast.get_docstring(node),
                class_name=self._class_stack[-1] if self._class_stack else None,
            )
        )
        self.generic_visit(node)  # also picks up nested functions

    # async def functions are handled the same way
    visit_AsyncFunctionDef = visit_FunctionDef


def _argument_names(args: ast.arguments) -> list[str]:
    names = [a.arg for a in args.posonlyargs + args.args]
    if args.vararg:
        names.append("*" + args.vararg.arg)
    names += [a.arg for a in args.kwonlyargs]
    if args.kwarg:
        names.append("**" + args.kwarg.arg)
    return names


def scan_file(path: Path, root: Path) -> list[FunctionInfo]:
    """Parse one file and return its functions. Raises SyntaxError if it cannot be parsed."""
    rel_path = path.relative_to(root).as_posix()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel_path)
    visitor = _FunctionVisitor(rel_path)
    visitor.visit(tree)
    return visitor.functions


def scan_repository(root: str | Path) -> ScanResult:
    """Scan every Python file under `root`. A file with a syntax error is recorded, not fatal."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    result = ScanResult(root=str(root))
    for path in find_python_files(root):
        rel = path.relative_to(root).as_posix()
        result.files.append(rel)
        try:
            result.functions.extend(scan_file(path, root))
        except (SyntaxError, UnicodeDecodeError) as exc:
            result.errors[rel] = f"{type(exc).__name__}: {exc}"
    return result

def get_function_source(root: str | Path, func: FunctionInfo) -> str:
    """Return the exact source lines of one function."""
    lines = (Path(root) / func.file).read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[func.start_line - 1 : func.end_line]) 


def _words(text: str) -> set[str]:
    """Split text into lowercase words, also splitting snake_case and CamelCase."""
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)  # CamelCase -> Camel Case
    return {w for w in re.split(r"[^a-zA-Z0-9]+", text.lower()) if len(w) > 2}


def search_functions(result: ScanResult, query: str, limit: int = 5) -> list[tuple[FunctionInfo, int]]:
    """Rank non-test functions by how many query words they share.

    Name match = 3 points, argument match = 2, docstring match = 1.
    Simple and transparent. On Day 2 the LLM refines the choice.
    """
    query_words = _words(query)
    scored = []
    for func in result.source_functions():
        score = (
            3 * len(query_words & _words(func.qualified_name))
            + 2 * len(query_words & _words(" ".join(func.args)))
            + 1 * len(query_words & _words(func.docstring or ""))
        )
        if score > 0:
            scored.append((func, score))
    scored.sort(key=lambda pair: (-pair[1], pair[0].file, pair[0].start_line))
    return scored[:limit]