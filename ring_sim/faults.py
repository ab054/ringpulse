"""Sync faults a real ring and radio produce. Each function takes a packet list and
returns a new one, so faults compose: reorder(duplicate(drop_seqs(packets, [3]), [1]))."""
import random
from typing import Any

Packets = list[dict[str, Any]]


def drop_seqs(packets: Packets, seqs: list[int]) -> Packets:
    """Lose specific packets (deterministic, for exact assertions)."""
    return [p for p in packets if p["seq"] not in seqs]


def drop_rate(packets: Packets, rate: float, seed: int = 0) -> Packets:
    """Lose each packet with probability `rate`."""
    rng = random.Random(seed)
    return [p for p in packets if rng.random() >= rate]


def duplicate(packets: Packets, seqs: list[int]) -> Packets:
    """Send the given packets twice (a retransmit after a missed ack)."""
    return packets + [p for p in packets if p["seq"] in seqs]


def reorder(packets: Packets, seed: int = 0) -> Packets:
    """Deliver packets in a shuffled order."""
    shuffled = list(packets)
    random.Random(seed).shuffle(shuffled)
    return shuffled


def corrupt(packets: Packets, seqs: list[int]) -> Packets:
    """Flip a bit in the checksum of the given packets (bit rot on the radio)."""
    return [{**p, "checksum": p["checksum"] ^ 1} if p["seq"] in seqs else p for p in packets]


def disconnect_after(packets: Packets, n: int) -> Packets:
    """The link drops after `n` packets. The rest stay on the ring for the next sync."""
    return packets[:n]
