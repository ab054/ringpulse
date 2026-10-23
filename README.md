# RingPulse

A tiny smart-ring system and the test system around it. The system is a toy; the tests are the point.

```
ring_sim (device)  ──sync packets──▶  api (cloud)  ──insights──▶  app (Android)
```

| Part | What it does |
|---|---|
| `ring_sim/` | Simulates a ring: generates a night of samples, sends them in numbered, checksummed packets, and can drop, duplicate, reorder or corrupt packets, or disconnect mid-sync |
| `api/` | FastAPI + SQLite. Rebuilds the night from packets and computes a sleep score and a readiness score (0–100) |
| `fixtures/nights/` | Named nights shared by every test layer: `good_night`, `short_night`, `restless_night`, `missing_data` |

## Run

```bash
pip install -r requirements-dev.txt
pytest                      # all tests
python -m ring_sim          # regenerate fixtures/nights/*.json (deterministic)

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
```

See [docs/test-plan.md](docs/test-plan.md) for scope, risks and exit criteria, and [docs/known-issues.md](docs/known-issues.md) for open findings.

## Sync protocol

`POST /sync` with `{device_id, night_id, total_packets, packets: [{seq, samples, checksum}]}`.

- A packet seen twice is ignored (`duplicates`); one with a bad checksum is rejected.
- Packets may arrive in any order; the night is rebuilt by `seq`.
- Missing sequence numbers give `sync_status: partial` and are listed in `missing_packets`. Sending the missing packets later completes the night.

`GET /nights/{night_id}` returns the sync status plus `sleep_score` and `readiness_score`.
