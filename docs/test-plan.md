# Test plan: sleep insights

**Feature:** a night recorded by the ring is synced to the cloud, turned into a sleep score and a readiness score (0–100), and shown in the app.
**Owner:** QA. **Status:** backend layers implemented; mobile and CI layers planned.

## 1. Scope

| In scope | Out of scope (for now) |
|---|---|
| Ring → API sync: packet loss, duplication, reordering, corruption, disconnects | Real Bluetooth: pairing, firmware versions, radio conditions. The emulator has none; see section 8 |
| Rebuilding a night from packets | Authentication and multi-user accounts (single toy user) |
| Sleep and readiness scoring, including the `v2` readiness flag | Real physiological accuracy of the formulas. The rules in `api/scoring.py` are the spec |
| Sync status shown to the user (`complete` / `partial`) | iOS |
| App screens that show scores and sync state (planned) | Load and soak testing beyond simple latency checks |

## 2. Risks and where each is covered

| # | Risk | Impact | Covered by |
|---|---|---|---|
| R1 | A score leaves 0–100 or becomes non-numeric for odd input | Wrong or broken insight shown | Unit: Hypothesis range property, hand-calculated cases |
| R2 | A score moves the wrong way (more HRV lowers readiness) | Misleading advice | Unit: monotonicity properties |
| R3 | Missing sensor data (HRV dropout, recording gaps) breaks scoring or silently skews it | Missing or wrong scores | Unit: component renormalisation; Data: `missing_data` night |
| R4 | Lost packets go unnoticed and a partial night looks complete | User trusts incomplete data | API: gap detection; Sync: exact loss reporting |
| R5 | Duplicated or reordered packets change the result | Double-counted sleep | API + Sync: duplicates ignored, order irrelevant, results identical to a clean sync |
| R6 | A corrupted packet is stored | Bad data in scores | Unit: checksum; API: rejected and not stored |
| R7 | A flaky link never recovers | Night stays partial forever | Sync: reconnect, retransmit and "bad sync then clean retry converges" tests |
| R8 | A formula change moves scores too far | Users see a jump after a release | Data: `v2` within 5 points of `v1` on every golden night |
| R9 | Ring and API disagree on the wire format | Every packet rejected in the field | Unit: contract test on checksums for all fixture packets |
| R10 | Wrong configuration breaks insights while `/health` is green | Silent outage | Known issue KI-1 (open) |
| R11 | The app shows stale or wrong state after sync problems | User confusion | E2E: partial-sync badge, later completion, API unreachable keeps last scores |
| R12 | Slow sync or slow app start | Poor experience | Performance (planned) |

## 3. Test layers

Every test carries one layer marker, enforced at collection time, so CI and test selection can pick layers (`pytest -m unit`).

| Layer (marker) | What it checks | Tools | Status |
|---|---|---|---|
| Unit (`unit`) | Scoring functions, packet parsing, checksum contract | Pytest, Hypothesis | Done |
| Data validation (`data`) | Scores for named nights against golden values within tolerance; flag comparison | Pytest + fixture nights | Done |
| API / integration (`api`) | Sync endpoint, rebuilding the night, error codes, persistence | Pytest + FastAPI test client | Done |
| Sync fault injection (`sync`) | Ring → API under packet loss, duplicates, reordering, corruption, disconnects | Ring simulator + Pytest | Done |
| Mobile E2E (`e2e`) | What the user sees on the phone after a sync | Appium (Python, UiAutomator2), Android emulator | Written; runs locally, not in CI yet. See [e2e-tests.md](e2e-tests.md) |
| Performance | Sync time for one night, app cold start | Pytest timing, `adb` | Planned |

## 4. Test data

Four named nights in `fixtures/nights/`, generated deterministically by `python -m ring_sim generate` and shared by every layer, so a failure at one layer can be traced to the others.

| Night | Purpose |
|---|---|
| `good_night` | Reference: 8 h, calm, HRV above baseline |
| `short_night` | Duration drives the scores down |
| `restless_night` | Efficiency, HRV and resting heart rate all hurt |
| `missing_data` | Two recording gaps and an HRV sensor dropout |

Golden values carry a tolerance of ±2 points. They were reviewed against the scoring rules when set (one worked out by hand) and must be changed deliberately, never by re-snapshotting the current output.

## 5. Environments

| Environment | Use |
|---|---|
| Local, in-process | API under Pytest with a temporary database per test |
| Docker Compose | The API as deployed (needs a running Docker daemon) |
| GitHub Actions | Every pull request and a nightly full run (planned) |
| Android emulator | App tests (run locally; CI planned); real devices in a device farm for the nightly run are a stretch goal |

## 6. Entry and exit criteria

**Entry (start testing a change):** the API starts, `/health` is green, fixtures regenerate without a diff.

**Exit (a change may merge):**
- All tests in the selected layers pass; a retried-then-passing test is flagged flaky, not silently green.
- No new open issue of high impact in `known-issues.md`.
- A change to scoring comes with updated expected values and the reason for them in the pull request.
- A change to the sync protocol updates the ring simulator and the contract test in the same pull request.

**Release (planned):** the nightly full run is green on `main`, and flaky count is not rising.

## 7. Exploratory charters

Short, time-boxed sessions for what scripted tests miss. Notes go to `known-issues.md`.

1. **Hostile packets** (30 min). Explore the sync endpoint with malformed, oversized and out-of-range input. Look for 500s, slow responses and data stored from rejected packets.
2. **Long and strange nights** (30 min). Explore nights of 1 minute, 20 hours, and with timestamps that jump backwards. Look for scores that do not make sense and efficiency above 100%.
3. **Configuration** (20 min). Explore flag values and environment mistakes. Starting point: KI-1.

## 8. What changes with real test rings

The simulator stands in for the ring, so these are untested here and would need real devices: BLE pairing and re-pairing, firmware versions that change the packet format, radio interference and range, battery-low behaviour, and clock drift between ring and phone. The sync-fault tests already model the symptoms (loss, duplicates, reordering, disconnects); real rings would show how often they happen and in what combinations.
