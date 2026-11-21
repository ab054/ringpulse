"""Turn one night of raw samples into the numbers the detector looks at.

Plain, deterministic code: this is the part of the AI layer that gets ordinary unit tests.
"""
import math
from dataclasses import dataclass
from typing import Any

# The single toy user's personal baselines (same idea as BASELINE_HRV / BASELINE_RHR in scoring).
BASELINE_RHR = 56.0  # bpm
BASELINE_HRV = 55.0  # ms
BASELINE_TEMP = 36.15  # degrees C, mean over a normal night
RESTLESS_MOVEMENT = 0.3


@dataclass(frozen=True)
class Features:
    rhr_delta: float  # resting HR minus baseline, bpm
    hrv_drop: float | None  # 1 - avg HRV / baseline; None when the HRV sensor gave nothing
    temp_delta: float | None  # mean temperature minus baseline, degrees C
    restless_share: float  # share of samples with high movement


def _get(sample: Any, key: str) -> Any:
    return sample.get(key) if isinstance(sample, dict) else getattr(sample, key)


def extract(samples: list[Any]) -> Features | None:
    """Features for a night, from dicts or api Sample objects. None if there is no heart rate at all."""
    hrs = sorted(_get(s, "hr") for s in samples if _get(s, "hr") is not None)
    if not hrs:
        return None
    lowest = hrs[: max(1, math.ceil(len(hrs) * 0.1))]
    hrvs = [_get(s, "hrv") for s in samples if _get(s, "hrv") is not None]
    temps = [_get(s, "temp") for s in samples if _get(s, "temp") is not None]
    moves = [_get(s, "movement") for s in samples if _get(s, "movement") is not None]
    return Features(
        rhr_delta=sum(lowest) / len(lowest) - BASELINE_RHR,
        hrv_drop=1 - (sum(hrvs) / len(hrvs)) / BASELINE_HRV if hrvs else None,
        temp_delta=sum(temps) / len(temps) - BASELINE_TEMP if temps else None,
        restless_share=sum(m >= RESTLESS_MOVEMENT for m in moves) / len(moves) if moves else 0.0,
    )
