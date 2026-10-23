# Known issues

Found while testing. Each has an ID so tests, PRs and the triage bot can refer to it.

| ID | Area | Issue | Impact | Status |
|---|---|---|---|---|
| KI-1 | API / feature flag | An unrecognised `RINGPULSE_READINESS_FORMULA` value (for example `v3`) raises an unhandled `KeyError`, so every `GET /nights/{id}` returns HTTP 500. The flag is read per request, so the API starts fine and fails later. | A typo in the deployment config breaks insights for all users while `/health` stays green. | Open. Fix: validate the flag at startup in `create_app` and fail fast. No test yet, because the intended behaviour (fail fast vs fall back to `v1`) needs a decision. |
| KI-2 | Scoring | Sleep efficiency is measured over the span between the first and last received sample. Packets lost at the end of a night shorten the span instead of counting as missing time, so a partial night's efficiency describes only what arrived and can differ from the full night's in either direction. Duration still drops. | Small: partial nights are labelled `partial` and the scores are recomputed when the missing packets arrive. | Open. To confirm with whoever owns the scoring rules whether partial nights should be scored at all. |
| KI-3 | Test suite | No test pins down result ordering when packets are read back (`ORDER BY seq`). SQLite returns rows in primary-key order anyway, so removing it changes nothing today, but another database could. | None on SQLite. | Accepted. Revisit if the database changes. |
