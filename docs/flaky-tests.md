# Flaky tests: retries, quarantine, health

A flaky test passes and fails on the same code. Left alone it blocks merges for no reason and teaches people to ignore red builds. Here every flake is seen, counted, and eventually contained, without hiding real failures.

## Retries

In CI a failed test is retried once (`pytest --reruns 1`, from `pytest-rerunfailures`; locally tests are **not** retried, so a failure on your machine is a real failure).

- Passes on the retry: the build stays green, but the test is recorded as **flaky** and listed in the job summary. It is never reported as a plain pass.
- Fails again: a real failure. A genuine regression fails every attempt, so one retry cannot hide it.

JUnit cannot tell these cases apart (each attempt is written as its own entry, and the failed first attempt looks like a pass), so `ci/test_results_plugin.py` keeps its own record: `--results-json` writes `{test: {status, attempts}}` with the statuses `passed`, `flaky`, `failed`, `skipped`, `quarantined_failed`, `quarantined_passed`.

## Quarantine

`quarantine.yaml` lists tests that still run but no longer block merges (they are marked non-strict `xfail`):

```yaml
quarantined:
  - tests/e2e/test_today_screen.py::test_sync_now_shows_the_scores_of_the_synced_night
```

An entry matches that exact test, or all parameter variants when it has no `[...]` part. The failure triage bot treats a failing quarantined test as `flaky` without asking the model. Quarantine is a holding pen, not a fix: the file is the to-do list.

## Health

Every run on `main`, nightly and manual runs add their results to `health.json`, stored on the `ci-health` branch (so recording history needs no pull request and does not touch `main`). Per test it keeps the last 30 results; the job summary shows the suite's first-time pass rate and the flakiest tests.

The nightly run also proposes quarantine changes in a pull request (`bot/quarantine-<run>`), for a person to review:

| Rule | Effect |
|---|---|
| Flaky 3 times in the window | Add to quarantine |
| Fails every time lately (last 3 results) | Not added: it is broken, not flaky |
| Quarantined, then 20 clean runs in a row | Proposed for release |
| Not seen for 30 days | Dropped from the history (renamed or deleted test) |

Run it by hand:

```bash
python -m ci.health report --health health.json
python -m ci.health quarantine --health health.json --file quarantine.yaml
```

## Setup (once)

In the repository settings, Actions → General → Workflow permissions, tick **Allow GitHub Actions to create and approve pull requests**. Without it the nightly job still records health, but cannot open the quarantine pull request (that step is allowed to fail so it never turns the nightly run red).

Only one quarantine pull request is open at a time, and none is opened when there is nothing to change. GitHub may hold the checks of a pull request opened by the bot until someone approves the run; the change is a small YAML edit, so review it like any other.

## Known limits

- One retry hides the *rate* of a flake, not its existence, which is why flaky results are counted and surfaced.
- Test health is recorded per run, not per commit, so a flake that appears only after a certain change needs a person to connect the two.
- `health.json` is a plain file on a branch. That is enough for this project; a database would be the next step at scale.
