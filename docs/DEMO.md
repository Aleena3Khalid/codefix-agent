# Demo script

A 3 to 4 minute screen recording that shows the agent working and explains the main design choices. Record the terminal and VS Code side by side.

## Before recording

- Make the terminal font large (Ctrl + plus in VS Code) so text is readable in the video.
- Clear the terminal (`cls`) and close unrelated windows and tabs.
- Check `git status` is clean, so the sample repo still has its bugs.
- Run `codefix fix sample_repo "..." --dry-run` once beforehand, so the first API call is not the slow one on camera.
- Recording on Windows: Win + Alt + R starts and stops Xbox Game Bar recording. OBS Studio also works and can record a selected area.

## Scenes

**1. The problem (20 s)**
Show `sample_repo/ISSUES.md`. Say: "This small repository has three bug reports written the way a user would write them. The agent's job is to find and fix the bug from the report alone."

**2. The tools without AI (30 s)**
```
codefix test sample_repo
codefix find sample_repo "free shipping not applied at exactly the threshold"
```
Say: "Day one was plain Python: parse the code with the ast module, rank functions against the report, and run the tests in a separate process with a timeout."

**3. The repair loop (60 s)**
```
codefix fix sample_repo "An order of exactly 50.00 is charged shipping, but the policy is free shipping for orders of at least 50."
```
Pause on each stage: the baseline, the proposed change, the sandbox test result, the diff. Say: "Every attempt is tested in a temporary copy. The real file only changes after it passes and I approve the diff." Type `y`.

Then:
```
git diff
```
Say: "The patch is a normal diff, so it can be reviewed like any code change." Then restore the bug:
```
git restore sample_repo
```

**4. What success means (30 s)**
Open `codefix/agent.py` at `compare_reports`. Say: "An early version accepted a partial fix that passed one test by coincidence. Now every failing test for the patched function must pass, with no regressions."

**5. The evaluation (45 s)**
Open `docs/EVALUATION.md`. Say: "Fifteen benchmark tasks, each with hidden tests the agent never sees, so a fix that only fools the visible tests is counted as incorrect." Point at the results table and the two bugs the evaluation found in the agent itself.

**6. API and CI (30 s)**
```
codefix serve
```
Open http://127.0.0.1:8000/docs in a browser and show the endpoints. Then show the green Actions run on GitHub. Say: "Eighty-nine tests run on Linux and Windows on every push, with fake models, so they are free and repeatable."

**7. Close (15 s)**
Say what you would do next: harder multi-function tasks, and measuring whether test feedback helps with logic errors.

## Afterwards

Upload the video (YouTube unlisted, Loom or similar) and add the link near the top of the README.
