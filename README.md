# CodeFix Agent

An agent that takes a bug report for a small Python repository, finds the relevant code, proposes a minimal patch, asks for approval, runs the tests and records the outcome.

Status: Day 1 of 5 (repository analyser and test runner).

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Mac/Linux: source .venv/bin/activate
pip install -e .
```

## Usage

```bash
codefix scan sample_repo
codefix find sample_repo "Discount makes the price tiny"
codefix show sample_repo apply_discount
codefix test sample_repo
codefix test sample_repo --json
```

## Project layout

```
codefix/
  analyzer.py      parses Python files with ast, lists functions, keyword search
  test_runner.py   runs pytest in a subprocess with a timeout, parses JUnit XML
  cli.py           command-line interface
tests/             tests for the tool itself
sample_repo/       small repo with 3 known bugs, used as the agent's target
  ISSUES.md        bug reports the agent will receive
```

## Running the tests

```bash
pytest
```

The tests in `sample_repo/` fail on purpose. They are the bugs the agent has to fix.