# Evaluation

This page describes how CodeFix Agent was evaluated, what the results were, and what they do and do not show.

## Method

**Benchmark.** 15 small bugs (5 easy, 7 medium, 3 hard), defined in `codefix/bench_tasks.py`. Each task is a tiny repository with buggy code, visible tests, a bug report written the way a user would write it, and hidden tests.

**Hidden tests.** The agent only sees the visible tests. After it finishes, hidden tests are added and run. This separates three outcomes:

- **correct**: passed the agent's own checks and the hidden tests
- **incorrect**: passed the agent's checks but failed a hidden test (a wrong fix that looked right)
- **failed**: no attempt passed the agent's checks

Three tasks are traps where a plausible fix passes the visible tests but not the hidden ones (`leap_year`, `mutable_default`, `median_two_bugs`), and one puts the symptom in a different function from the bug (`price_helper`).

**Task validity.** `codefix bench-check` confirms, for every task, that the bug makes a visible test fail and that a reference fix passes every visible and hidden test. This also runs in the test suite.

**Configurations compared.**

- **single** (baseline): one model call, no retries
- **agent**: up to 3 attempts, with test results fed back after a failed attempt

**Models.** claude-sonnet-5-5 (15 tasks, 1 repeat) and claude-haiku-5-5 (15 tasks, 3 repeats).

**Reproducing.**

```
codefix bench-check
codefix evaluate --model claude-sonnet-5-5
codefix evaluate --model claude-haiku-5-5 --repeats 3
```

Each run writes `report.md`, `results.json`, `results.csv` and one log per task to `eval_results/<timestamp>/`. The report records the date, model and git commit.

## Results

| | Sonnet single | Sonnet agent | Haiku single | Haiku agent |
|---|---|---|---|---|
| Correct | 15/15 | 15/15 | 39/45 (87%) | 42/45 (93%) |
| Incorrect | 0 | 0 | 1 | 2 |
| Failed | 0 | 0 | 5 | 1 |
| Attempts rejected before testing | 0 | 0 | 5 | 11 |
| Mean attempts | 1 | 1 | 1 | 1.22 |
| Total tokens | 27,530 | 27,568 | 86,205 | 107,276 |
| Total cost | $0.098 | $0.098 | not recorded | not recorded |

Sonnet costs use the price table in `codefix/llm.py`, which should be checked against Anthropic's current pricing. Haiku has no entry in that table, so its cost is not reported.

## Findings

**1. Sonnet fixed every task on the first attempt.** With Sonnet the two configurations gave identical results, so this benchmark is too easy to measure the value of the repair loop for that model.

**2. With Haiku, every failed attempt was a formatting failure.** In all 5 single failures and all 11 rejected agent attempts, the model wrote a fix but put the code inside the `root_cause` field and left `fixed_code` empty. The answers were rejected by the agent's checks before any tests ran. In the cases inspected, the misplaced code was a correct fix. No attempt by either configuration produced a well formed fix that then failed the visible tests.

**3. The repair loop's benefit was recovery from malformed output.** It reduced failures from 5 to 1 by asking again after a rejected answer, at a cost of 24% more tokens. On this benchmark it never had to correct a wrong fix, so these results do not show whether test feedback helps the model fix logic errors.

**4. Incorrect fixes came from one task.** All 3 incorrect fixes were on `mutable_default`, in 3 of its 6 Haiku runs. Its only hidden test checks that the input list is not modified, which the docstring promises. These fixes removed the shared default argument but still changed the caller's list.

**5. Results vary between runs.** The same task with the same configuration sometimes succeeded and sometimes failed (for example `leap_year` and `mutable_default`). The gap between Haiku single and agent is 3 runs out of 45 and should be read as a tendency, not a measured difference.

## Bugs found by the evaluation

- **Indented method code rejected.** The first Sonnet run scored 14/15 for single. The run log showed a correct fix for `Account.withdraw` rejected because the model returned the method with its class indentation, which the validation step could not parse. The patcher already handled this case, but validation did not. Fixed by dedenting before parsing, with a regression test. After the fix both configurations scored 15/15.
- **Unclear feedback for empty answers.** When `fixed_code` was empty, the feedback only said the code did not contain the expected function. It now states that `fixed_code` is empty and the code must go in that field. The report also gained a row counting attempts rejected before testing, so formatting failures are not confused with wrong fixes.

## Limitations

- **Small benchmark.** 15 single-function bugs in tiny repositories. Real bugs often span several functions or files.
- **Easy for strong models.** Sonnet scored 100%, so the benchmark cannot separate configurations for that model. Harder tasks are needed.
- **Linking tests to functions is by name.** The agent treats a failing test as related to a function if the test's code mentions the function's name. Tests that reach a function indirectly are missed.
- **Keyword search for candidate functions.** Candidates are chosen by shared words between the bug report and function names, arguments and docstrings. Vague reports fall back to sending all functions, which only works for small repositories.
- **One prompt, one model family.** Results may differ with other prompts or models.
- **Formatting failures are handled by retrying.** The agent does not try to recover code from the wrong field, to avoid hiding model errors. Stricter schema enforcement for tool calls, if the API offers it for these models, could remove this failure mode.

## Possible next steps

- Add harder tasks: multi-function bugs, bugs without tests that point at them, and larger repositories.
- Measure whether test feedback helps with logic errors, using tasks where first attempts produce well formed but wrong fixes.
- Run with more repeats and report a range rather than a single rate.
