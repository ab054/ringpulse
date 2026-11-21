"""The "model": a logistic score over the night's features, weights loaded from ai/models/<version>.json.

The weights file is the model artifact. Changing it changes behaviour without touching code, which
is exactly why a model version needs its own gate (ai/evaluate.py), not just the unit tests.
"""
import json
import math
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from ai.features import Features, extract

MODELS_DIR = Path(__file__).resolve().parent / "models"
LABEL = "illness_signs"


@dataclass(frozen=True)
class Detection:
    label: str | None  # LABEL when the score crosses the model's threshold, else None
    confidence: float  # 0..1
    model_version: str


@lru_cache
def load_model(version: str) -> dict[str, Any]:
    path = MODELS_DIR / f"{version}.json"
    if not path.exists():
        known = sorted(p.stem for p in MODELS_DIR.glob("*.json"))
        raise ValueError(f"unknown model version {version!r}; known: {known}")
    return json.loads(path.read_text())


def active_version() -> str:
    """The model the API serves. Validated when the app starts (same fail-fast rule as the readiness flag)."""
    version = os.environ.get("RINGPULSE_MODEL", "v1")
    load_model(version)
    return version


def score(features: Features, model: dict[str, Any]) -> float:
    w = model["weights"]
    # A missing sensor contributes its "imputed" value: the model decides what silence means.
    hrv_drop = features.hrv_drop if features.hrv_drop is not None else model["impute"]["hrv_drop"]
    temp_delta = features.temp_delta if features.temp_delta is not None else model["impute"]["temp_delta"]
    z = (
        model["bias"]
        + w["rhr_delta"] * features.rhr_delta
        + w["hrv_drop"] * hrv_drop
        + w["temp_delta"] * temp_delta
        + w["restless_share"] * features.restless_share
    )
    return 1 / (1 + math.exp(-z))


def detect(samples: list[Any], version: str) -> Detection | None:
    """None when the night has nothing to judge (no heart rate)."""
    features = extract(samples)
    if features is None:
        return None
    model = load_model(version)
    confidence = score(features, model)
    label = LABEL if confidence >= model["threshold"] else None
    return Detection(label=label, confidence=round(confidence, 3), model_version=version)
