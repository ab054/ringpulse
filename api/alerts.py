"""Alert rules: pure functions from (analysis, clock) to alerts, plus dedup and delivery.

Kept pure on purpose: the rules are where business decisions live, so they get table-driven
tests with a frozen clock and no database, network or model.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import yaml

RULES_PATH = Path(__file__).resolve().parent / "alert_rules.yaml"
log = logging.getLogger("ringpulse.alerts")


@lru_cache
def load_rules(path: str = str(RULES_PATH)) -> dict[str, Any]:
    config = yaml.safe_load(Path(path).read_text())
    known = {"detection", "readiness_below", "no_data_for_hours"}
    for rule in config["rules"]:
        if rule["when"] not in known:
            raise ValueError(f"rule {rule['id']}: unknown condition {rule['when']!r}")
    return config


@dataclass(frozen=True)
class NightResult:
    device_id: str
    night_id: str
    readiness: int | None
    detection_label: str | None
    detection_confidence: float | None


@dataclass(frozen=True)
class Candidate:
    """An alert a rule wants to raise, before dedup decides whether it is new."""
    rule_id: str
    severity: str
    message: str
    night_id: str | None = None


def evaluate_night(result: NightResult, config: dict[str, Any]) -> list[Candidate]:
    out = []
    for rule in config["rules"]:
        if rule["when"] == "detection":
            fired = (result.detection_label is not None
                     and result.detection_confidence is not None
                     and result.detection_confidence >= rule["min_confidence"])
        elif rule["when"] == "readiness_below":
            fired = result.readiness is not None and result.readiness < rule["threshold"]
        else:
            continue  # device-level rules are checked by silent_devices
        if fired:
            out.append(Candidate(rule["id"], rule["severity"], rule["message"], result.night_id))
    return out


def silent_devices(last_seen: dict[str, datetime], now: datetime, config: dict[str, Any]) -> list[tuple[str, Candidate]]:
    out = []
    for rule in config["rules"]:
        if rule["when"] != "no_data_for_hours":
            continue
        limit = timedelta(hours=rule["hours"])
        for device_id, seen in sorted(last_seen.items()):
            if now - seen > limit:
                out.append((device_id, Candidate(rule["id"], rule["severity"], rule["message"])))
    return out


def record(conn: sqlite3.Connection, device_id: str, candidate: Candidate, now: datetime,
           config: dict[str, Any]) -> dict[str, Any] | None:
    """Store the alert unless the same rule fired for this device inside the dedup window.

    Returns the new alert (to be delivered), or None when it was folded into an existing one.
    """
    window_start = now - timedelta(hours=config["dedup_window_hours"])
    existing = conn.execute(
        "SELECT id FROM alerts WHERE device_id = ? AND rule_id = ? AND last_seen_at >= ? ORDER BY id DESC LIMIT 1",
        (device_id, candidate.rule_id, window_start.isoformat()),
    ).fetchone()
    if existing:
        conn.execute("UPDATE alerts SET occurrences = occurrences + 1, last_seen_at = ? WHERE id = ?",
                     (now.isoformat(), existing["id"]))
        return None
    cursor = conn.execute(
        "INSERT INTO alerts (device_id, rule_id, severity, message, night_id, created_at, last_seen_at, occurrences)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
        (device_id, candidate.rule_id, candidate.severity, candidate.message, candidate.night_id,
         now.isoformat(), now.isoformat()),
    )
    return {"id": cursor.lastrowid, "device_id": device_id, "rule_id": candidate.rule_id,
            "severity": candidate.severity, "message": candidate.message, "night_id": candidate.night_id}


class Notifier(Protocol):
    def send(self, alert: dict[str, Any]) -> None: ...


class LogNotifier:
    """Stands in for push / email / SMS. Real channels would sit behind the same one-method interface."""

    def send(self, alert: dict[str, Any]) -> None:
        log.info("alert %s for %s: %s", alert["rule_id"], alert["device_id"], alert["message"])


@dataclass
class RecordingNotifier:
    """Test double: remembers what would have been sent."""
    sent: list[dict[str, Any]] = field(default_factory=list)

    def send(self, alert: dict[str, Any]) -> None:
        self.sent.append(alert)
