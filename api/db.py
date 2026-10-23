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
