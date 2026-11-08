# CodeFix Agent

[![tests](https://github.com/Aleena3Khalid/codefix-agent/actions/workflows/tests.yml/badge.svg)](https://github.com/Aleena3Khalid/codefix-agent/actions/workflows/tests.yml)

An AI agent that takes a bug report for a small Python repository, finds the relevant code, proposes a minimal fix, tests it in a sandbox, retries with feedback if it fails, and applies it only after a human approves the diff.

```
$ codefix fix sample_repo "An order of exactly 50.00 is charged shipping, but the policy is free shipping for orders of at least 50."
Running tests to get a baseline...
Baseline: 8 passed, 4 failed, 0 errors

Attempt 1/3: asking the model...
  Proposed change to cart.py :: qualifies_for_free_shipping (confidence high)
  Sandbox tests: 9 passed, 3 failed. Fixed 1, still failing 0, regressions 0.

Attempt 1 passed in the sandbox. Fixed: tests/test_cart.py::test_free_shipping_at_threshold. Regressions: none.

Proposed patch:
--- a/cart.py
+++ b/cart.py
@@ -15,7 +15,7 @@
 
 def qualifies_for_free_shipping(total, threshold=50):
     """Orders of at least `threshold` ship for free."""
-    return total > threshold
+    return total >= threshold
 
 
 class Cart:

Apply this patch to cart.py? [y/N] y

Status: fixed
Tests in sample_repo now: 9 passed, 3 failed
1 attempt(s), 1 LLM call(s), 1771 in / 521 out tokens, $0.0088, 24.056s total
```

## How it works

```
bug report
   |
   v
1. Inspect    parse the repo with Python's ast module, list functions,
              rank them against the bug report, run the tests for a baseline
   |
   v
2. Reason     send the bug report, the candidate functions and the failing
              test output to Claude; get a structured diagnosis back
              (file, function, root cause, fixed code) through tool calling
   |
   v
3. Check      reject answers that name a missing function, do not parse,
              or contain the wrong function; turn the fix into a unified diff
   |
   v
4. Test       copy the repo to a temporary sandbox, apply the patch there,
              run the tests, compare with the baseline
   |
   +-- failed --> send the failure back to the model, try again (max 3)
   |
   v
5. Approve    show the diff to a human; apply to the real repo only on "y"
   |
   v
6. Record     write a JSON log of every attempt, diff, test result and cost
```

### When does a fix count as working?

A fix is accepted only if all of these hold:

- at least one failing test now passes
- every failing test that uses the patched function now passes (a partial fix is not a fix)
- no test that passed before now fails (no regressions)
- the tests did not time out
- no tests disappeared (a broken import can make failing tests vanish from the results)

The second rule was added after an early version accepted `total - percent` as a fix for a discount bug: it passed the 0% test by coincidence and still failed the 10% test.

### Safety

- **Sandbox first.** Every attempt runs in a fresh temporary copy of the repository. The real files are never touched while the agent experiments.
- **Limited attempts.** At most 3 attempts per run (configurable), so a confused model cannot loop and spend indefinitely.
- **Human approval.** The real repository changes only after a patch has passed in the sandbox and a person has approved the diff. The default answer is no.
- **Stale check.** A patch is not applied if the file changed after the patch was made.
- **Validated model output.** Model answers are checked before use. Invalid answers are rejected and the reason is fed back to the model.

## Evaluation

Measured on a benchmark of 15 small bugs, each with **hidden tests** that the agent never sees. A fix that passes the visible tests but fails the hidden ones is counted as **incorrect**.

| | Sonnet single | Sonnet agent | Haiku single | Haiku agent |
|---|---|---|---|---|
| Correct | 15/15 | 15/15 | 39/45 (87%) | 42/45 (93%) |
| Incorrect | 0 | 0 | 1 | 2 |
| Failed | 0 | 0 | 5 | 1 |

*single* = one model call; *agent* = up to 3 attempts with test feedback. Haiku was run 3 times per task.

Main findings:

- Sonnet fixed every task first time, so this benchmark cannot show the value of retries for that model.
- With Haiku, every failed attempt was a formatting failure (code returned in the wrong field), not a wrong fix. The repair loop's benefit was recovering from these.
- The evaluation found two bugs in the agent itself, both now fixed with regression tests.

Full method, results and limitations: [docs/EVALUATION.md](docs/EVALUATION.md).

## Quick start

Requires Python 3.10 or newer and an [Anthropic API key](https://console.anthropic.com/).

```bash
git clone https://github.com/Aleena3Khalid/codefix-agent.git
cd codefix-agent
python -m venv .venv
.venv\Scripts\activate          # Mac/Linux: source .venv/bin/activate
pip install -e .
copy .env.example .env          # Mac/Linux: cp .env.example .env
# then put your key in .env
```

Check it works without spending anything:

```bash
pytest                    # runs the test suite with fake models
codefix test sample_repo  # 8 passed, 4 failed: the sample repo has 3 known bugs
```

## Commands

| Command | What it does | Uses the API |
|---|---|---|
| `codefix scan sample_repo` | list the functions in a repository | no |
| `codefix find sample_repo "free shipping threshold"` | rank functions related to a description | no |
| `codefix show sample_repo apply_discount` | print a function's source | no |
| `codefix test sample_repo` | run the tests and summarise the result | no |
| `codefix diagnose sample_repo "<bug report>"` | diagnosis and proposed fix, changes nothing | yes |
| `codefix fix sample_repo "<bug report>"` | full repair loop with approval | yes |
| `codefix fix ... --dry-run` / `--yes` | never apply / apply without asking | yes |
| `codefix bench-check` | check every benchmark task is valid | no |
| `codefix evaluate` | run the benchmark and write a report | yes |
| `codefix serve` | start the web API | per request |

Add `--log-level INFO` before the command for detailed logs, for example `codefix --log-level INFO fix ...`. Use `--model` on `diagnose`, `fix` and `evaluate` to choose a model.

## Web API

```bash
codefix serve
```

Interactive documentation is generated at http://127.0.0.1:8000/docs.

| Endpoint | Purpose |
|---|---|
| `GET /health` | service status |
| `POST /scan` | `{"repo": "sample_repo"}` lists functions |
| `POST /diagnose` | `{"repo": ..., "issue": ...}` returns a diagnosis |
| `POST /fix` | `{"repo": ..., "issue": ..., "apply": false}` runs the repair loop |

`/fix` is a dry run unless the request sends `"apply": true`, which plays the role of the approval prompt. Repository paths must be inside `CODEFIX_REPOS_ROOT` (default: the folder the server was started in).

## Project layout

```
codefix/
  analyzer.py      parse Python files with ast, list functions, keyword search
  test_runner.py   run pytest in a subprocess with a timeout, parse JUnit XML
  llm.py           wrapper for every model call: tokens, cost, latency
  assistant.py     bug report -> prompt -> structured diagnosis -> validation
  patcher.py       turn a proposed function into a diff; apply safely
  agent.py         the repair loop: sandbox, comparison, retries, approval, logs
  bench_tasks.py   the 15 benchmark tasks with hidden tests
  evaluate.py      run the benchmark, classify outcomes, write reports
  api.py           FastAPI endpoints
  cli.py           command-line interface
tests/             89 tests, none of which call the real API
sample_repo/       small repository with 3 known bugs for demos
docs/              evaluation write-up and demo script
```

## Testing

```bash
pytest
```

The test suite uses fake models (scripted answers, an "oracle" that returns known fixes, and deliberately wrong "trap" answers), so it is fast, free and gives the same result every time. GitHub Actions runs it on Linux and Windows with Python 3.10 and 3.13 on every push. Running on Windows matters: a line-ending bug in one of the tests only appeared there.

## Limitations

- Fixes are limited to a single function per attempt.
- Candidate functions are found by keyword overlap with the bug report; vague reports fall back to sending all functions, which only suits small repositories.
- Tests are linked to a function by name, so tests that reach it indirectly are not counted as related.
- The benchmark is small and too easy for the strongest model tested.
- The agent depends on the model filling in the structured answer correctly; malformed answers are rejected and retried rather than repaired.
- Costs use a hard-coded price table in `codefix/llm.py` that must be kept up to date.

## Built with

Python, the Anthropic API (tool calling for structured output), pytest, FastAPI and GitHub Actions.
