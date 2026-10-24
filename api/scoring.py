"""Sleep and readiness scores. Pure functions, deliberately simple so expected values
can be worked out by hand in tests.

Sleep score     = 0.7 * duration + 0.3 * efficiency      (duration: 8 h = 100)
Readiness score = weighted mix of HRV vs baseline, resting HR vs baseline, duration.
                  A component with no data is dropped and the remaining weights are
                  renormalised.
"""
import math
from dataclasses import dataclass

from api.models import Sample
from api.protocol import SAMPLE_INTERVAL_MIN

TARGET_SLEEP_H = 8.0
BASELINE_HRV = 55.0  # ms, single toy user
BASELINE_RHR = 56.0  # bpm
ASLEEP_MOVEMENT = 0.3  # a sample counts as sleep below this movement level

# v2 is the "new formula" behind the feature flag: leans harder on HRV.
READINESS_WEIGHTS = {
    "v1": {"hrv": 0.4, "rhr": 0.3, "duration": 0.3},
    "v2": {"hrv": 0.5, "rhr": 0.2, "duration": 0.3},
}


@dataclass(frozen=True)
class NightMetrics:
    sleep_minutes: int
    efficiency: float  # asleep samples / samples in the night's time span, 0..1
    avg_hrv: float | None  # mean HRV over asleep samples
    resting_hr: float | None  # mean of the lowest 10% of heart-rate readings


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def round_half_up(x: float) -> int:
    return math.floor(x + 0.5)


def compute_metrics(samples: list[Sample]) -> NightMetrics | None:
    """Reduce a night of samples to the numbers the scores need. None if no samples."""
    if not samples:
        return None

    asleep = [s for s in samples if s.movement is not None and s.movement < ASLEEP_MOVEMENT]
    span = (max(s.t for s in samples) - min(s.t for s in samples)) // SAMPLE_INTERVAL_MIN + 1
    efficiency = min(1.0, len(asleep) / span)

    hrvs = [s.hrv for s in asleep if s.hrv is not None]
    hrs = sorted(s.hr for s in samples if s.hr is not None)
    lowest = hrs[: max(1, math.ceil(len(hrs) * 0.1))]

    return NightMetrics(
        sleep_minutes=(len(asleep) - 1) * SAMPLE_INTERVAL_MIN,
        efficiency=efficiency,
        avg_hrv=sum(hrvs) / len(hrvs) if hrvs else None,
        resting_hr=sum(lowest) / len(lowest) if lowest else None,
    )


def duration_component(m: NightMetrics) -> float:
    return clamp(100 * (m.sleep_minutes / 60) / TARGET_SLEEP_H)


def sleep_score(m: NightMetrics) -> int:
    return round_half_up(clamp(0.7 * duration_component(m) + 0.3 * 100 * m.efficiency))


def readiness_score(m: NightMetrics, formula: str = "v1") -> int:
    weights = READINESS_WEIGHTS[formula]
    components: dict[str, float] = {"duration": duration_component(m)}
    if m.avg_hrv is not None:
        components["hrv"] = clamp(80 + 100 * (m.avg_hrv / BASELINE_HRV - 1))
    if m.resting_hr is not None:
        components["rhr"] = clamp(80 - 4 * (m.resting_hr - BASELINE_RHR))

    total_weight = sum(weights[k] for k in components)
    blended = sum(weights[k] * v for k, v in components.items()) / total_weight
    return round_half_up(clamp(blended))
