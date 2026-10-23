"""The ring's side of the sync protocol: split a night into numbered, checksummed packets."""
import json
import zlib
from typing import Any

PACKET_SIZE = 12  # samples per packet; one hour of data at 5-minute resolution


def checksum(samples: list[dict[str, Any]]) -> int:
    payload = json.dumps(samples, sort_keys=True, separators=(",", ":")).encode()
    return zlib.crc32(payload) & 0xFFFFFFFF


def make_packets(samples: list[dict[str, Any]], size: int = PACKET_SIZE) -> list[dict[str, Any]]:
    chunks = [samples[i : i + size] for i in range(0, len(samples), size)]
    return [{"seq": seq, "samples": chunk, "checksum": checksum(chunk)} for seq, chunk in enumerate(chunks)]
