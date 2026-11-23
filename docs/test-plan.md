# Test plan: sleep insights

**Feature:** a night recorded by the ring is synced to the cloud, turned into a sleep score and a readiness score (0–100), and shown in the app. A complete night is also analysed by a small model for illness signs, and alert rules decide whether the user is told.
**Owner:** QA. **Status:** all layers implemented and running in CI; performance checks planned.

## 1. Scope

| In scope | Out of scope (for now) |
|---|---|
| Ring → API sync: packet loss, duplication, reordering, corruption, disconnects | Real Bluetooth: pairing, firmware versions, radio conditions. The emulator has none; see section 8 |
| Rebuilding a night from packets | Authentication and multi-user accounts (single toy user) |
| Sleep and readiness scoring, including the `v2` readiness flag | Real physiological accuracy of the formulas. The rules in `api/scoring.py` are the spec |
| Sync status shown to the user (`complete` / `partial`) | iOS |
| App screens that show scores and sync state | Load and soak testing beyond simple latency checks |
| Processing queue, the illness-signs detector and its versions, alert rules and dedup, `GET /alerts` | A real trained model and its real accuracy: the detector is a stand-in with hand-set weights |
| Model quality per slice on a labelled eval set, and the gate for a new model version | Alerts on screen and real notification channels (push, email): the app does not show alerts yet |

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
| R10 | Wrong configuration breaks insights while `/health` is green | Silent outage | API: unknown readiness flag or model version fails at startup (KI-1, fixed) |
| R11 | The app shows stale or wrong state after sync problems | User confusion | E2E: partial-sync badge, later completion, API unreachable keeps last scores |
| R12 | Slow sync or slow app start | Poor experience | Performance (planned) |
| R13 | A new model version is better on average but worse for one condition | Missed illness for some users after a model release | Data: per-slice gate on the labelled eval set (`v2` is rejected for the HRV-dropout slice) |
| R14 | A dead sensor makes a sick night look healthy | Missed alert | Unit: missing HRV is `None`, not zero; Data: `hrv_dropout` slice |
| R15 | A complete night is never analysed, or analysed twice | Missing or duplicate alerts | API: queued once when complete, not before; a repeat sync queues nothing |
| R16 | The same condition alerts again and again | Alert fatigue, users turn alerts off | Unit: dedup inside and outside the 24 h window; API: two sick nights in a day give one alert with a count |
| R17 | An alert reaches the wrong user | Privacy breach | Unit: dedup never crosses devices; API: `GET /alerts` returns one device's alerts only |
| R18 | A threshold in the alert rules is off by one | Alerts fire too early or never | Unit: both sides of every threshold in `api/alert_rules.yaml` |
| R19 | A device stops syncing and nobody notices | Silence looks like "all fine" | Unit + API: `device_silent` after 36 h, not at 35 h |
| R20 | One broken night stops the processing queue | No analysis or alerts for anyone | Worker marks the job `failed` and continues (by design; no dedicated test yet) |

## 3. Test layers

Every test carries one layer marker, enforced at collection time, so CI and test selection can pick layers (`pytest -m unit`).

| Layer (marker) | What it checks | Tools | Status |
|---|---|---|---|
| Unit (`unit`) | Scoring functions, packet parsing, checksum contract, the code around the model (features, loading, scoring), alert-rule tables | Pytest, Hypothesis | Done |
| Data validation (`data`) | Scores for named nights against golden values within tolerance; flag comparison; model quality per slice and the model gate | Pytest + fixture nights + labelled eval set | Done |
| API / integration (`api`) | Sync endpoint, rebuilding the night, error codes, persistence; the queue → model → alerts pipeline | Pytest + FastAPI test client | Done |
| Sync fault injection (`sync`) | Ring → API under packet loss, duplicates, reordering, corruption, disconnects | Ring simulator + Pytest | Done |
| Mobile E2E (`e2e`) | What the user sees on the phone after a sync | Appium (Python, UiAutomator2), Android emulator | Done, runs in CI on an emulator. Alerts are not on screen yet. See [e2e-tests.md](e2e-tests.md) |
| Performance | Sync time for one night, app cold start | Pytest timing, `adb` | Planned |

## 4. Test data

Four named nights in `fixtures/nights/`, generated deterministically by `python -m ring_sim generate` and shared by every layer, so a failure at one layer can be traced to the others.

| Night | Purpose |
|---|---|
| `good_night` | Reference: 8 h, calm, HRV above baseline |
| `short_night` | Duration drives the scores down |
| `restless_night` | Efficiency, HRV and resting heart rate all hurt |
| `missing_data` | Two recording gaps and an HRV sensor dropout |

The model is checked on a separate **labelled eval set** (`ai/evalset.py`): 150 simulated nights with a known answer (ill or healthy), in five slices: calm, restless, ill, mild_ill, hrv_dropout. It is generated deterministically from case ids, so the code is its version. See [ai-and-alerts.md](ai-and-alerts.md).

Golden values carry a tolerance of ±2 points. They were reviewed against the scoring rules when set (one worked out by hand) and must be changed deliberately, never by re-snapshotting the current output.

## 5. Environments

| Environment | Use |
|---|---|
| Local, in-process | API under Pytest with a temporary database per test |
| Docker Compose | The API as deployed (needs a running Docker daemon) |
| GitHub Actions | Every pull request (selected layers) and a nightly full run |
| Android emulator | App tests, locally and in CI; real devices in a device farm for the nightly run are a stretch goal |

## 6. Entry and exit criteria

**Entry (start testing a change):** the API starts, `/health` is green, fixtures regenerate without a diff.

**Exit (a change may merge):**
- All tests in the selected layers pass; a retried-then-passing test is flagged flaky, not silently green.
- No new open issue of high impact in `known-issues.md`.
- A change to scoring comes with updated expected values and the reason for them in the pull request.
- A change to the sync protocol updates the ring simulator and the contract test in the same pull request.
- A new model version passes the model gate against the current one (`python -m ai.evaluate --candidate <new>`).
- A change to an alert threshold updates its boundary tests in the same pull request.

**Release:** the nightly full run is green on `main`, and flaky count is not rising.

## 7. Exploratory charters

Short, time-boxed sessions for what scripted tests miss. Notes go to `known-issues.md`.

1. **Hostile packets** (30 min). Explore the sync endpoint with malformed, oversized and out-of-range input. Look for 500s, slow responses and data stored from rejected packets.
2. **Long and strange nights** (30 min). Explore nights of 1 minute, 20 hours, and with timestamps that jump backwards. Look for scores that do not make sense and efficiency above 100%.
3. **Configuration** (20 min). Explore flag values and environment mistakes. Starting point: KI-1.
4. **Alert noise** (30 min). Sync many sick, borderline and silent nights for several devices, move the clock, and read `GET /alerts` as a user would. Look for alerts that repeat, arrive for the wrong device, or never clear.

## 8. What changes with real test rings

The simulator stands in for the ring, so these are untested here and would need real devices: BLE pairing and re-pairing, firmware versions that change the packet format, radio interference and range, battery-low behaviour, and clock drift between ring and phone. The sync-fault tests already model the symptoms (loss, duplicates, reordering, disconnects); real rings would show how often they happen and in what combinations.
