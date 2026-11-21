"""The model's quality, measured on the labelled eval set (ai/evalset.py) and gated per slice.

These are statistical checks against thresholds, not exact answers: that is how a model is
tested. The functional tests elsewhere never depend on the model being right.
"""
import pytest

from ai.evalset import PER_SLICE, SLICES, build
from ai.evaluate import RECALL_FLOOR, evaluate, gate, overall_recall

pytestmark = pytest.mark.data


@pytest.fixture(scope="module")
def cases():
    return build()  # read-only, so sharing it across the module is safe


@pytest.fixture(scope="module")
def production(cases):
    return evaluate("v1", cases)


def test_eval_set_is_deterministic_and_balanced(cases):
    again = build()
    assert [c.samples for c in cases] == [c.samples for c in again]
    assert {s: sum(c.slice == s for c in cases) for s in SLICES} == {s: PER_SLICE for s in SLICES}


def test_production_model_meets_the_recall_floor(production):
    assert overall_recall(production) >= RECALL_FLOOR


def test_production_model_raises_no_false_alarms_on_calm_nights(production):
    assert production["calm"].rate == 0


def test_gate_rejects_a_candidate_that_is_better_on_average_but_worse_on_a_slice(cases, production):
    # v2 catches more mild cases, so its overall recall goes up...
    v2 = evaluate("v2", cases)
    assert overall_recall(v2) > overall_recall(production)
    # ...but it treats a dead HRV sensor as "healthy", and the gate must see that slice.
    problems = gate(v2, production)
    assert problems and all("hrv_dropout" in p for p in problems)


def test_gate_accepts_the_fixed_candidate(cases, production):
    assert gate(evaluate("v3", cases), production) == []


def test_gate_accepts_the_production_model_against_itself(production):
    assert gate(production, production) == []
