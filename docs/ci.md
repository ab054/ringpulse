# Continuous integration

Workflow: `.github/workflows/ci.yml`. It answers one question on every pull request: *which tests can this change break?* and runs only those.

## What runs when

| Trigger | What runs |
|---|---|
| Pull request | Only the layers the changed files can affect |
| Pull request with label `run-all-tests` | Everything |
| Push to `main` | Everything |
| Nightly (03:17 UTC) | Everything |
| Manual ("Run workflow") | Everything |

```
select ──┬──▶ backend  (pytest -m "<selected unit/data/api/sync layers>")
         └──▶ mobile   (build APK → emulator + Appium → pytest -m e2e)     only if e2e was selected
                          ▼
                       result   (one stable check for branch protection)
```

The emulator job is the reason selection exists: it takes many minutes, while the backend layers take seconds.

## How tests are selected

`ci/select_tests.py` reads `ci/test_map.yaml`, a list of path globs and the layers each one can affect, and compares it to the files changed in the pull request. It is plain code, not a model: the same diff always gives the same answer, and the map can be read and reviewed.

- The first rule that matches a file decides its layers, so specific rules sit above general ones.
- Every run writes a table to the job summary: each changed file, the layers it selected, and why.

Safety rules beat the map. These all run **everything**:

- the file is not in the map (a new, unmapped area is more dangerous than an extra run)
- the diff is empty or cannot be computed
- the event is not a pull request
- the label `run-all-tests` is set
- the change touches shared plumbing: `tests/conftest.py`, `pytest.ini`, requirements, the workflow

A test (`tests/ci/`) fails if any tracked file is missing from the map, so adding a new folder forces a decision about which layers it affects.

Try it locally:

```bash
python -m ci.select_tests --files api/scoring.py README.md
python -m ci.select_tests --base origin/main --head HEAD
```

## When the emulator job fails

Open the run, then download the `e2e-artifacts` artifact: screenshots, page source, logcat for each failed test, plus `appium.log` and `junit.xml` (see [e2e-tests.md](e2e-tests.md)). In CI `E2E_REQUIRED=1` is set, so a missing emulator or APK fails the job instead of silently skipping tests.

## Branch protection

Require the check **CI result** on `main`. It is green when every job that had to run passed; jobs skipped by selection count as passed.
