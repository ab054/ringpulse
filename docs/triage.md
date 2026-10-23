# Failure triage bot

When a backend or emulator test fails on a pull request, a bot reads the failure, decides **who is wrong, the test or the app**, proposes a small fix, and checks that fix by re-running the failed test. It posts one comment. **It never pushes and never merges: a person decides.**

Code: `triage/`. Job: `triage` in `.github/workflows/ci.yml`. Tests: `tests/triage/` (a fake model stands in, so they need no key).

## The steps

| # | Step | Model? | What it does |
|---|---|---|---|
| 1 | Bundle (`bundle.py`) | no | Reads the JUnit reports. For each failed test: id, assertion message, trace, the test's own source, and for emulator tests the saved page source and logcat tail |
| 2 | Pre-filter (`prefilter.py`) | no | Known causes get a label for free: a test listed in `quarantine.yaml` is `flaky`; "no Appium server", "connection refused" and similar are `environment` |
| 3 | Diagnosis (`diagnose.py`) | yes | One call per remaining failure, with `prompt.md` and a required JSON answer (`schema.json`). The pull request title, description and diff are in the prompt, so an intended behaviour change is recognised |
| 4 | Verify (`verify.py`) | no | Checks the patch against rules, applies it to a throw-away copy of the repo and re-runs only the failed test |
| 5 | Report (`report.py`) | no | One comment: a summary table, then root cause, quoted evidence and the patch per failure |

The model's answer:

| Field | Values |
|---|---|
| `category` | `app_regression`, `test_bug`, `intended_change`, `flaky`, `environment` |
| `fix_target` | `app`, `test`, `none` |
| `root_cause`, `evidence`, `patch`, `confidence` | short text, quoted lines, a unified diff, `low`/`medium`/`high` |

`intended_change` is the interesting one: the PR changed behaviour on purpose, so the test's expected value should be updated, and the comment asks the reviewer to confirm the change with whoever owns the behaviour.

Fix check results: **fix verified** (the failed test passes with the patch), **fix did not help**, **patch rejected** (breaks a rule or does not apply), **not attempted** (no patch, or an emulator test, which cannot be re-run in this job).

## Guardrails

- Runs only when a test job failed, on pull requests from this repository (forks get no secrets).
- At most 5 failures per run go to the model, with capped diff size and output tokens. Prompt, schema and default model (`claude-sonnet-5-5`, override with `TRIAGE_MODEL`) are in the repo.
- Credentials are scrubbed from everything sent to the model.
- PR text is untrusted: it is sent inside tags the prompt declares as data. This lowers prompt-injection risk, it does not remove it, which is one more reason nothing is applied automatically.
- A patch may not touch `.github/`, `ci/`, `triage/` or requirements files, may not delete files, an app fix may not edit tests (that would hide the failure), and a test fix may only edit tests or fixtures.
- A model answer that is not valid JSON in the schema is retried once, then reported as "no usable answer". Any crash inside the bot is logged and the step still exits 0, so a broken bot never replaces the real failure.

## Setup (once)

1. Create an Anthropic API key and **set a monthly spend limit on it first**. Triage runs cost cents.
2. Repository → Settings → Secrets and variables → Actions → New repository secret: `ANTHROPIC_API_KEY`.

Without the secret the job still runs and the comment says there is no diagnosis; the pre-filter labels still work.

## Known limits

- Emulator-test fixes are diagnosed but not verified (no emulator in this job).
- The patch is shown in a collapsible block, not yet as a one-click GitHub suggestion.
- The "apply this fix" command (a bot PR against the author's branch) is not built.
- `quarantine.yaml` is read if present; nothing creates it yet (the flaky-quarantine bot is a later step).
