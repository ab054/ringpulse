import sqlite3
from contextlib import contextmanager
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS nights (
    night_id      TEXT PRIMARY KEY,
    device_id     TEXT NOT NULL,
    total_packets INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS packets (
    night_id     TEXT NOT NULL REFERENCES nights(night_id),
    seq          INTEGER NOT NULL,
    checksum     INTEGER NOT NULL,
    samples_json TEXT NOT NULL,
    PRIMARY KEY (night_id, seq)
);
CREATE TABLE IF NOT EXISTS devices (
    device_id    TEXT PRIMARY KEY,
    last_seen_at TEXT NOT NULL
);
-- Work queue between ingest and the AI layer: one job per night, written when the night is complete.
CREATE TABLE IF NOT EXISTS jobs (
    night_id   TEXT PRIMARY KEY REFERENCES nights(night_id),
    status     TEXT NOT NULL,  -- pending | done | failed
    created_at TEXT NOT NULL,
    error      TEXT
);
CREATE TABLE IF NOT EXISTS analyses (
    night_id      TEXT PRIMARY KEY REFERENCES nights(night_id),
    model_version TEXT NOT NULL,
    label         TEXT,
    confidence    REAL,
    readiness     INTEGER,
    analysed_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id    TEXT NOT NULL,
    rule_id      TEXT NOT NULL,
    severity     TEXT NOT NULL,
    message      TEXT NOT NULL,
    night_id     TEXT,
    created_at   TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    occurrences  INTEGER NOT NULL
);
"""


class Store:
    """SQLite file with one short-lived connection per request (thread-safe by construction)."""

    def __init__(self, path: str):
        self.path = path
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
