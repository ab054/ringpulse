"""Step 2, plain Python: failures with a known cause get a label without a model call (keeps cost near zero)."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

# (pattern, why). Matched against the failure message and traceback.
ENVIRONMENT_PATTERNS = [
    (r"No Appium server at", "the Appium server never came up"),
    (r"No debug APK at", "the app was not built"),
    (r"Appium did not start", "the Appium server never came up"),
    (r"port 8000 is already in use|did not become healthy|API did not start", "the API could not start for the test"),
    (r"Connection refused|ConnectError", "a service the test needs was not reachable"),
    (r"adb: (no devices|device offline)|Could not find a connected Android device", "no emulator was available"),
]


def load_quarantine(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return set((yaml.safe_load(path.read_text()) or {}).get("quarantined", []))


def prefilter(failure: dict, quarantined: set[str]) -> dict | None:
    """A ready diagnosis dict, or None when the failure needs the model."""
    if failure["id"] in quarantined:
        return _label("flaky", "The test is in the quarantine list, so it is a known flaky test.")
    text = failure["message"] + "\n" + failure["traceback"]
    for pattern, why in ENVIRONMENT_PATTERNS:
        if re.search(pattern, text):
            return _label("environment", f"The test could not run properly: {why}.")
    return None


def _label(category: str, root_cause: str) -> dict:
    return {"category": category, "fix_target": "none", "root_cause": root_cause, "evidence": [],
            "patch": "", "confidence": "high", "source": "prefilter"}
