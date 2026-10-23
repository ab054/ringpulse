"""Synthetic nights for the ring simulator.

Deterministic: the same profile always gives the same night. Run
`python -m ring_sim generate` to (re)write fixtures/nights/*.json.
"""
import json
import math
import random
from pathlib import Path
from typing import Any

INTERVAL_MIN = 5
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "nights"
DEVICE_ID = "ring-sim-01"

# restless: share of samples with high movement. gaps: (start index, length) windows where the
# ring recorded nothing. hrv_dropout: window where the HRV sensor returned nothing.
PROFILES: dict[str, dict[str, Any]] = {
    "good_night": dict(
        description="8 h, calm, HRV slightly above baseline",
        hours=8.0, hr=53.0, hrv=58.0, restless=0.04, gaps=[], hrv_dropout=None,
    ),
    "short_night": dict(
        description="4.5 h, calm but far too short",
        hours=4.5, hr=57.0, hrv=50.0, restless=0.08, gaps=[], hrv_dropout=None,
    ),
    "restless_night": dict(
        description="7.5 h, lots of movement, low HRV, high heart rate",
        hours=7.5, hr=61.0, hrv=38.0, restless=0.35, gaps=[], hrv_dropout=None,
    ),
    "missing_data": dict(
        description="8 h with two recording gaps and a 1-hour HRV sensor dropout",
        hours=8.0, hr=54.0, hrv=56.0, restless=0.05, gaps=[(20, 8), (60, 10)], hrv_dropout=(40, 12),
    ),
}

# Golden values the data-validation tests check (readiness is the v1 formula). Reviewed against
# the scoring rules after generation, with good_night's readiness worked out by hand
# (0.4*91.7 + 0.3*91.0 + 0.3*96.9 = 93.0). Update them deliberately, never by re-snapshotting.
EXPECTED: dict[str, dict[str, int]] = {
    "good_night": {"sleep_score": 97, "readiness_score": 93, "tolerance": 2},
    "short_night": {"sleep_score": 66, "readiness_score": 71, "tolerance": 2},
    "restless_night": {"sleep_score": 60, "readiness_score": 58, "tolerance": 2},
    "missing_data": {"sleep_score": 75, "readiness_score": 85, "tolerance": 2},
}


def build_night(name: str) -> dict[str, Any]:
    p = PROFILES[name]
    rng = random.Random(name)
    count = int(p["hours"] * 60 / INTERVAL_MIN)
    dropped = {i for start, length in p["gaps"] for i in range(start, start + length)}
    samples = []
    for i in range(count):
        if i in dropped:
            continue
        phase = i / count
        hr = p["hr"] + 4 * abs(math.cos(math.pi * phase)) + rng.gauss(0, 1.2)
        hrv = p["hrv"] + 6 * math.sin(math.pi * phase) + rng.gauss(0, 3)
        restless = rng.random() < p["restless"]
        movement = 0.5 + rng.random() * 0.5 if restless else rng.random() * 0.2
        temp = 36.4 - 0.4 * math.sin(math.pi * phase) + rng.gauss(0, 0.05)
        in_dropout = p["hrv_dropout"] and p["hrv_dropout"][0] <= i < sum(p["hrv_dropout"])
        samples.append({
            "t": i * INTERVAL_MIN,
            "hr": round(hr, 1),
            "hrv": None if in_dropout else round(max(hrv, 5.0), 1),
            "movement": round(movement, 2),
            "temp": round(temp, 2),
        })
    return {
        "name": name,
        "description": p["description"],
        "night_id": f"night-{name.replace('_', '-')}",
        "device_id": DEVICE_ID,
        "interval_min": INTERVAL_MIN,
        "samples": samples,
        "expected": EXPECTED.get(name),
    }


def load_night(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text())


def write_fixtures() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    for name in PROFILES:
        night = build_night(name)
        (FIXTURES_DIR / f"{name}.json").write_text(json.dumps(night, indent=1) + "\n")
        print(f"wrote {name}: {len(night['samples'])} samples")
