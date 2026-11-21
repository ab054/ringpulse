"""Alert rules as tables: input -> which alerts. Frozen clock, in-memory database, no model.

Each threshold in api/alert_rules.yaml has a test on both sides of its boundary.
"""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from api.alerts import Candidate, NightResult, evaluate_night, load_rules, record, silent_devices
from api.db import SCHEMA

pytestmark = pytest.mark.unit

RULES = load_rules()
T0 = datetime(2026, 11, 20, 7, 0, tzinfo=timezone.utc)


def result(readiness=80, label=None, confidence=None):
    return NightResult("ring-a", "night-1", readiness, label, confidence)


@pytest.mark.parametrize("night, expected", [
    pytest.param(result(), [], id="healthy-night-no-alert"),
    pytest.param(result(label="illness_signs", confidence=0.80), ["illness_signs"], id="detection-at-threshold"),
    pytest.param(result(label="illness_signs", confidence=0.79), [], id="detection-below-confidence"),
    pytest.param(result(label=None, confidence=0.95), [], id="high-score-but-no-label"),
    pytest.param(result(readiness=59), ["low_readiness"], id="readiness-just-below"),
    pytest.param(result(readiness=60), [], id="readiness-at-threshold"),
    pytest.param(result(readiness=None), [], id="no-readiness-no-alert"),
    pytest.param(result(readiness=40, label="illness_signs", confidence=0.9), ["illness_signs", "low_readiness"],
                 id="both-rules-fire"),
])
def test_night_rules(night, expected):
    assert [c.rule_id for c in evaluate_night(night, RULES)] == expected


@pytest.mark.parametrize("silent_for, fires", [
    pytest.param(timedelta(hours=36), False, id="exactly-at-limit"),
    pytest.param(timedelta(hours=36, minutes=1), True, id="just-past-limit"),
    pytest.param(timedelta(hours=2), False, id="recently-seen"),
])
def test_device_silence(silent_for, fires):
    out = silent_devices({"ring-a": T0 - silent_for}, T0, RULES)
    assert [(d, c.rule_id) for d, c in out] == ([("ring-a", "device_silent")] if fires else [])


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    yield c
    c.close()


ILL = Candidate("illness_signs", "high", "msg", "night-1")


def test_repeat_inside_the_window_is_folded_into_one_alert(conn):
    first = record(conn, "ring-a", ILL, T0, RULES)
    again = record(conn, "ring-a", ILL, T0 + timedelta(hours=23), RULES)

    assert first is not None and again is None
    row = conn.execute("SELECT occurrences FROM alerts").fetchone()
    assert row["occurrences"] == 2


def test_repeat_after_the_window_is_a_new_alert(conn):
    record(conn, "ring-a", ILL, T0, RULES)

    assert record(conn, "ring-a", ILL, T0 + timedelta(hours=24, minutes=1), RULES) is not None
    assert conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 2


def test_dedup_never_crosses_devices(conn):
    record(conn, "ring-a", ILL, T0, RULES)

    assert record(conn, "ring-b", ILL, T0, RULES) is not None


def test_different_rules_are_not_deduplicated_together(conn):
    record(conn, "ring-a", ILL, T0, RULES)
    low = Candidate("low_readiness", "medium", "msg", "night-1")

    assert record(conn, "ring-a", low, T0, RULES) is not None


def test_unknown_rule_condition_is_refused(tmp_path):
    bad = tmp_path / "rules.yaml"
    bad.write_text("dedup_window_hours: 24\nrules:\n  - {id: x, when: moon_phase, severity: low, message: m}\n")

    with pytest.raises(ValueError, match="moon_phase"):
        load_rules(str(bad))
