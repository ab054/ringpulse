"""Sync protocol constants shared by the API's validation code.

The ring simulator has its own copy of `checksum` on purpose: device and cloud are
separate components, and a contract test (step 2) checks that the two agree.
"""
import json
import zlib
from typing import Any

SAMPLE_INTERVAL_MIN = 5


def checksum(samples: list[dict[str, Any]]) -> int:
    """CRC32 over the canonical JSON of the raw samples as they arrived on the wire."""
    payload = json.dumps(samples, sort_keys=True, separators=(",", ":")).encode()
    return zlib.crc32(payload) & 0xFFFFFFFF
