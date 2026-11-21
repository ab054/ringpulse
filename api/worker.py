"""The processing step between ingest and alerts.

/sync only stores packets and, when a night becomes complete, puts a job in the `jobs` table.
This worker picks jobs up, runs the AI layer, stores the analysis and applies the alert rules.
Like a real ingest pipeline, it is asynchronous: tests wait for the result by condition, never by sleep.

`process_pending` and `check_silence` are plain functions, so tests can also run one step directly
and deterministically; the background thread only calls them in a loop.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from typing import Any, Callable

from ai.detector import detect
from api import alerts
from api.db import Store
from api.models import Sample
from api.scoring import compute_metrics, readiness_score

Clock = Callable[[], datetime]
log = logging.getLogger("ringpulse.worker")


def enqueue(conn, night_id: str, now: datetime) -> None:
    conn.execute("INSERT OR IGNORE INTO jobs (night_id, status, created_at) VALUES (?, 'pending', ?)",
                 (night_id, now.isoformat()))


def process_pending(store: Store, clock: Clock, notifier: alerts.Notifier, *, model_version: str,
                    formula: str, rules: dict[str, Any] | None = None) -> int:
    """Analyse every pending night. Returns how many jobs were processed."""
    rules = rules or alerts.load_rules()
    with store.connect() as conn:
        jobs = [r["night_id"] for r in conn.execute("SELECT night_id FROM jobs WHERE status = 'pending' ORDER BY rowid")]
    for night_id in jobs:
        to_send: list[dict[str, Any]] = []
        try:
            with store.connect() as conn:
                device_id = conn.execute("SELECT device_id FROM nights WHERE night_id = ?", (night_id,)).fetchone()["device_id"]
                rows = conn.execute("SELECT samples_json FROM packets WHERE night_id = ? ORDER BY seq", (night_id,))
                samples = [Sample.model_validate(raw) for row in rows for raw in json.loads(row["samples_json"])]
                metrics = compute_metrics(samples)
                readiness = readiness_score(metrics, formula) if metrics else None
                detection = detect(samples, model_version)
                now = clock()
                conn.execute(
                    "INSERT OR REPLACE INTO analyses (night_id, model_version, label, confidence, readiness, analysed_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (night_id, model_version, detection.label if detection else None,
                     detection.confidence if detection else None, readiness, now.isoformat()),
                )
                result = alerts.NightResult(device_id, night_id, readiness,
                                            detection.label if detection else None,
                                            detection.confidence if detection else None)
                for candidate in alerts.evaluate_night(result, rules):
                    alert = alerts.record(conn, device_id, candidate, now, rules)
                    if alert:
                        to_send.append(alert)
                conn.execute("UPDATE jobs SET status = 'done' WHERE night_id = ?", (night_id,))
        except Exception as exc:  # one bad night must not stop the queue
            log.exception("job for %s failed", night_id)
            with store.connect() as conn:
                conn.execute("UPDATE jobs SET status = 'failed', error = ? WHERE night_id = ?", (repr(exc), night_id))
            continue
        for alert in to_send:  # deliver only after the transaction committed
            notifier.send(alert)
    return len(jobs)


def check_silence(store: Store, clock: Clock, notifier: alerts.Notifier, rules: dict[str, Any] | None = None) -> int:
    rules = rules or alerts.load_rules()
    now = clock()
    sent = 0
    with store.connect() as conn:
        last_seen = {r["device_id"]: datetime.fromisoformat(r["last_seen_at"])
                     for r in conn.execute("SELECT device_id, last_seen_at FROM devices")}
        to_send = [a for device_id, candidate in alerts.silent_devices(last_seen, now, rules)
                   if (a := alerts.record(conn, device_id, candidate, now, rules))]
    for alert in to_send:
        notifier.send(alert)
        sent += 1
    return sent


class Worker:
    """Runs process_pending and check_silence every `interval` seconds until stopped."""

    def __init__(self, step: Callable[[], None], interval: float = 0.5):
        self._step = step
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ringpulse-worker", daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._step()
            except Exception:
                log.exception("worker step failed")
            self._stop.wait(self._interval)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
