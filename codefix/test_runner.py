"""Run a repository's tests in a separate process and summarise the result.

Why a subprocess instead of importing pytest directly?
- Isolation: the code under test cannot crash or modify our tool's process.
- Timeout: an infinite loop in a bad patch is killed after `timeout` seconds.
- Clean imports: every run starts fresh, so a patched file is really re-imported.

Why JUnit XML instead of reading pytest's printed output?
Printed output is meant for humans and changes between versions. JUnit XML is
a stable, machine-readable report that pytest writes with `--junitxml`.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# Keep only the end of long outputs; enough to see the failure, small enough to send to an LLM later.
MAX_OUTPUT_CHARS = 8000


@dataclass
class TestReport:
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration_s: float = 0.0
    exit_code: int | None = None
    timed_out: bool = False
    failed_tests: list[str] = field(default_factory=list)  # e.g. "tests/test_cart.py::test_discount"
    output: str = ""

    # Tell pytest this class is not a test case even though its name starts with "Test".
    __test__ = False

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.errors + self.skipped

    @property
    def pass_rate(self) -> float:
        ran = self.passed + self.failed + self.errors
        return self.passed / ran if ran else 0.0

    @property
    def all_passed(self) -> bool:
        return not self.timed_out and self.failed == 0 and self.errors == 0 and self.passed > 0

    def to_dict(self) -> dict:
        data = asdict(self)
        data.update(total=self.total, pass_rate=round(self.pass_rate, 3), all_passed=self.all_passed)
        return data


def run_tests(repo: str | Path, target: str = ".", timeout: int = 60) -> TestReport:
    """Run pytest inside `repo` and return a TestReport.

    `target` can be "." (everything), a file like "tests/test_cart.py", or a
    single test like "tests/test_cart.py::test_discount".
    """
    repo = Path(repo).resolve()
    if not repo.is_dir():
        raise NotADirectoryError(f"Not a directory: {repo}")

    with tempfile.TemporaryDirectory() as tmp:
        xml_path = Path(tmp) / "report.xml"
        cmd = [
            sys.executable, "-m", "pytest", target,
            "-q",
            f"--junitxml={xml_path}",
            "--rootdir", str(repo),
            "-p", "no:cacheprovider",  # do not write a .pytest_cache folder into the target repo
        ]
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

        log.debug("Running tests in %s (target=%s, timeout=%ss)", repo, target, timeout)
        start = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd, cwd=repo, env=env, capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired as exc:
            partial = (exc.stdout or b"")
            if isinstance(partial, bytes):
                partial = partial.decode(errors="replace")
            log.warning("Tests in %s timed out after %ss", repo, timeout)
            return TestReport(
                duration_s=round(time.perf_counter() - start, 3),
                timed_out=True,
                output=_tail(partial + f"\n[codefix] Tests timed out after {timeout}s"),
            )
        duration = round(time.perf_counter() - start, 3)

        report = _parse_junit(xml_path) if xml_path.exists() else TestReport()
        report.duration_s = duration
        report.exit_code = proc.returncode
        report.output = _tail(proc.stdout + proc.stderr)

        # pytest exit codes: 0 ok, 1 tests failed, 2 interrupted, 3 internal error,
        # 4 usage error, 5 no tests collected. If pytest crashed before writing
        # any results, count that as an error so it is never mistaken for success.
        if report.total == 0 and proc.returncode not in (0, 5):
            report.errors = 1
        log.info("Tests in %s: %d passed, %d failed, %d errors (%.2fs)",
                 repo.name, report.passed, report.failed, report.errors, report.duration_s)
        return report


def _parse_junit(xml_path: Path) -> TestReport:
    report = TestReport()
    root = ET.parse(xml_path).getroot()
    for case in root.iter("testcase"):
        test_id = _test_id(case)
        if case.find("failure") is not None:
            report.failed += 1
            report.failed_tests.append(test_id)
        elif case.find("error") is not None:
            report.errors += 1
            report.failed_tests.append(test_id)
        elif case.find("skipped") is not None:
            report.skipped += 1
        else:
            report.passed += 1
    return report


def _test_id(case: ET.Element) -> str:
    """Turn JUnit's classname ("tests.test_cart") + name into a pytest id."""
    classname = case.get("classname", "")
    name = case.get("name", "")
    parts = classname.split(".")
    # Find the module part (starts with test_) to rebuild the file path.
    for i, part in enumerate(parts):
        if part.startswith("test_") or part.endswith("_test"):
            file_path = "/".join(parts[: i + 1]) + ".py"
            rest = parts[i + 1 :]  # class names, if the test is inside a class
            return "::".join([file_path, *rest, name])
    return f"{classname}::{name}" if classname else name


def _tail(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT_CHARS else "...\n" + text[-MAX_OUTPUT_CHARS:]
