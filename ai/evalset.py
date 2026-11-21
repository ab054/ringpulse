"""The labelled eval set: nights from the ring simulator with a known answer.

Each case is generated deterministically from its id, so the set is versioned by this file alone
(no large data in git). Slices are the conditions a single average would hide:

  calm         ordinary healthy nights                       label: no
  restless     healthy but restless, HR a little up         label: no   (hard negatives)
  ill          illness signs: HR up, HRV down, temp up       label: yes
  mild_ill     weaker illness signs                          label: yes  (hard positives)
  hrv_dropout  ill nights where the HRV sensor gave nothing  label: yes
"""
import random
from dataclasses import dataclass
from typing import Any

from ring_sim.generate import synth_samples

EVALSET_VERSION = "2026-11-21"
PER_SLICE = 30


@dataclass(frozen=True)
class Case:
    case_id: str
    slice: str
    label: bool  # True = illness signs present
    samples: list[dict[str, Any]]


def _profile(slice_name: str, rng: random.Random) -> dict[str, Any]:
    u = rng.uniform
    base = dict(hours=u(6.5, 8.5), restless=u(0.02, 0.08), gaps=[], hrv_dropout=None)
    if slice_name == "calm":
        return base | dict(hr=u(52, 57), hrv=u(50, 62), temp=u(36.30, 36.55))
    if slice_name == "restless":
        return base | dict(hr=u(55, 59), hrv=u(42, 52), temp=u(36.35, 36.60), restless=u(0.25, 0.4))
    if slice_name == "ill":
        return base | dict(hr=u(59, 65), hrv=u(32, 44), temp=u(36.80, 37.30))
    if slice_name == "mild_ill":
        return base | dict(hr=u(56.5, 60), hrv=u(42, 50), temp=u(36.60, 36.85))
    if slice_name == "hrv_dropout":
        return base | dict(hr=u(58, 63), hrv=u(32, 44), temp=u(36.70, 37.10), hrv_dropout=(0, 200))
    raise ValueError(slice_name)


SLICES = {"calm": False, "restless": False, "ill": True, "mild_ill": True, "hrv_dropout": True}


def build() -> list[Case]:
    cases = []
    for slice_name, label in SLICES.items():
        for i in range(PER_SLICE):
            case_id = f"{slice_name}-{i:02d}"
            rng = random.Random(f"{EVALSET_VERSION}/{case_id}")
            samples = synth_samples(_profile(slice_name, rng), rng)
            cases.append(Case(case_id, slice_name, label, samples))
    return cases
