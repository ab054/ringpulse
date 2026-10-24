# RingPulse

A tiny smart-ring system and the test system around it. The system is a toy; the tests are the point.

```
ring_sim (device)  ──sync packets──▶  api (cloud)  ──insights──▶  app (Android)
```

| Part | What it does |
|---|---|
| `ring_sim/` | Simulates a ring: generates a night of samples, sends them in numbered, checksummed packets, and can drop, duplicate, reorder or corrupt packets, or disconnect mid-sync |
| `api/` | FastAPI + SQLite. Rebuilds the night from packets and computes a sleep score and a readiness score (0–100) |
| `app/` | Android app (Kotlin, Compose): a Today screen with the two scores, a sync badge and a Sync now button. See [docs/android-app.md](docs/android-app.md) |
| `fixtures/nights/` | Named nights shared by every test layer: `good_night`, `short_night`, `restless_night`, `missing_data` |

## Run

```bash
pip install -r requirements-dev.txt
pytest                      # all tests
python -m ring_sim generate                   # regenerate fixtures/nights/*.json (deterministic)
python -m ring_sim sync good_night            # sync a fixture night to a running API (--drop 3,5 loses packets)

# API in Docker
docker compose up --build
curl localhost:8000/health
```

Readiness has a feature flag: `RINGPULSE_READINESS_FORMULA=v2` switches to the new weights.

## Tests

Every test has a layer marker, so you can run one layer at a time:

```bash
pytest -m unit    # scoring and packet parsing, incl. Hypothesis properties
pytest -m data    # golden nights within tolerance
pytest -m api     # sync endpoint over HTTP
pytest -m sync    # ring simulator faults: loss, duplicates, reordering, corruption, disconnects
pytest -m e2e     # the app on an Android emulator via Appium (skipped when no emulator setup is found)
```

The emulator tests need an emulator, an Appium server and the debug APK: see [docs/e2e-tests.md](docs/e2e-tests.md).

CI runs on GitHub Actions and, on pull requests, picks only the test layers a change can affect: see [docs/ci.md](docs/ci.md).

Failed tests are retried once in CI; a pass on retry is recorded as flaky, flaky tests can be quarantined, and a health report tracks first-try pass rate over time: see [docs/flaky-tests.md](docs/flaky-tests.md).

When a test fails on a PR, a bot diagnoses it (test bug, app regression, intended change, flaky, environment), tries its suggested fix in a scratch copy and comments: see [docs/triage.md](docs/triage.md).

See [docs/test-plan.md](docs/test-plan.md) for scope, risks and exit criteria, and [docs/known-issues.md](docs/known-issues.md) for open findings.

## Sync protocol

`POST /sync` with `{device_id, night_id, total_packets, packets: [{seq, samples, checksum}]}`.

- A packet seen twice is ignored (`duplicates`); one with a bad checksum is rejected.
- Packets may arrive in any order; the night is rebuilt by `seq`.
- Missing sequence numbers give `sync_status: partial` and are listed in `missing_packets`. Sending the missing packets later completes the night.

`GET /nights/{night_id}` returns the sync status plus `sleep_score` and `readiness_score`. `GET /nights/latest` returns the same for the night that most recently received a packet; the app's Today screen uses it.
