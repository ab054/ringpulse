"""Things in the workflow that silently change under us if left loose."""
import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit
WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"


def test_runners_are_pinned_not_latest():
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    for name, job in jobs.items():
        assert not job["runs-on"].endswith("-latest"), f"{name}: pin the runner image (e.g. ubuntu-24.04)"


def test_every_action_is_pinned_to_a_major_version():
    uses = re.findall(r"uses:\s*(\S+)", WORKFLOW.read_text())
    assert uses
    for action in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@v\d+", action), f"{action} is not pinned to a major version"
