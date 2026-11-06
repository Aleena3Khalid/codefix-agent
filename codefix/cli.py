"""Command-line interface.

Examples (run from the project folder):
    codefix scan sample_repo
    codefix find sample_repo "discount percentage wrong"
    codefix show sample_repo apply_discount
    codefix test sample_repo
    codefix test sample_repo --json
"""

from __future__ import annotations

import argparse
import json
import sys

from codefix.analyzer import get_function_source, scan_repository, search_functions
from codefix.test_runner import run_tests


def cmd_scan(args: argparse.Namespace) -> int:
    result = scan_repository(args.repo)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    print(f"Repository: {result.root}")
    print(f"Python files: {len(result.files)}")
    funcs = result.functions if args.include_tests else result.source_functions()
    current_file = None
    for f in funcs:
        if f.file != current_file:
            current_file = f.file
            print(f"\n{current_file}")
        print(f"  L{f.start_line:<4} {f.qualified_name}({', '.join(f.args)})")
    print(f"\n{len(result.source_functions())} functions, {len(result.test_functions())} tests")
    for file, err in result.errors.items():
        print(f"[parse error] {file}: {err}", file=sys.stderr)
    return 1 if result.errors else 0


def cmd_find(args: argparse.Namespace) -> int:
    result = scan_repository(args.repo)
    matches = search_functions(result, args.query, limit=args.limit)
    if args.json:
        print(json.dumps([{**f.to_dict(), "score": s} for f, s in matches], indent=2))
        return 0
    if not matches:
        print("No matching functions.")
        return 1
    for func, score in matches:
        print(f"[{score}] {func.file}:{func.start_line} {func.qualified_name}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    result = scan_repository(args.repo)
    hits = [f for f in result.functions if args.name in (f.name, f.qualified_name)]
    if not hits:
        print(f"No function named {args.name!r}.", file=sys.stderr)
        return 1
    for func in hits:
        print(f"# {func.file}:{func.start_line}-{func.end_line}")
        print(get_function_source(result.root, func))
        print()
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    report = run_tests(args.repo, target=args.target, timeout=args.timeout)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        status = "TIMED OUT" if report.timed_out else ("PASS" if report.all_passed else "FAIL")
        print(f"{status}: {report.passed} passed, {report.failed} failed, "
              f"{report.errors} errors, {report.skipped} skipped "
              f"({report.pass_rate:.0%} pass rate, {report.duration_s}s)")
        for test_id in report.failed_tests:
            print(f"  x {test_id}")
        if args.verbose:
            print("\n" + report.output)
    return 0 if report.all_passed else 1

def cmd_diagnose(args: argparse.Namespace) -> int:
    from codefix.assistant import diagnose  # imported here so other commands work without the API package
    from codefix.llm import LLM

    diag = diagnose(args.repo, args.issue, llm=LLM(model=args.model), include_tests=not args.no_tests)
    if args.json:
        print(json.dumps(diag.to_dict(), indent=2))
        return 0 if not diag.warnings else 1

    print(f"Summary:    {diag.summary}")
    print(f"Location:   {diag.file} :: {diag.function}")
    print(f"Confidence: {diag.confidence}")
    print(f"\nRoot cause:\n{diag.root_cause}")
    print(f"\nProposed fix:\n{diag.fixed_code}")
    for warning in diag.warnings:
        print(f"\n[warning] {warning}", file=sys.stderr)
    if diag.usage:
        u = diag.usage
        cost = f"${u.cost_usd:.4f}" if u.cost_usd is not None else "unknown cost"
        print(f"\n[{u.model}] {u.input_tokens} in / {u.output_tokens} out tokens, {cost}, {u.latency_s}s")
    return 0 if not diag.warnings else 1

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codefix", description="Inspect and test small Python repos.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scan", help="List functions in a repository")
    p.add_argument("repo")
    p.add_argument("--include-tests", action="store_true", help="Also list test functions")
    p.add_argument("--json", action="store_true")
    p.set_defaults(handler=cmd_scan)

    p = sub.add_parser("find", help="Find functions related to a description")
    p.add_argument("repo")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--json", action="store_true")
    p.set_defaults(handler=cmd_find)

    p = sub.add_parser("show", help="Print the source of a function")
    p.add_argument("repo")
    p.add_argument("name", help="Function name, or Class.method")
    p.set_defaults(handler=cmd_show)

    p = sub.add_parser("test", help="Run the repository's tests")
    p.add_argument("repo")
    p.add_argument("--target", default=".", help="File or test id to run (default: all)")
    p.add_argument("--timeout", type=int, default=60)
    p.add_argument("--json", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true", help="Show pytest output")
    p.set_defaults(handler=cmd_test)

    p = sub.add_parser("diagnose", help="Ask the LLM to diagnose a bug and propose a fix")
    p.add_argument("repo")
    p.add_argument("issue", help="The bug report text")
    p.add_argument("--model", default=None, help="Model id (default: CODEFIX_MODEL or claude-sonnet-5-5)")
    p.add_argument("--no-tests", action="store_true", help="Do not run tests or send their output")
    p.add_argument("--json", action="store_true")
    p.set_defaults(handler=cmd_diagnose)
    
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        from dotenv import load_dotenv

        # reads ANTHROPIC_API_KEY from a .env file in the current folder
        load_dotenv()
    except ImportError:
        pass
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())