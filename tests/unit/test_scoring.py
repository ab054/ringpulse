import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from api.models import Sample
from api.scoring import (
    ASLEEP_MOVEMENT,
    NightMetrics,
    compute_metrics,
    readiness_score,
    sleep_score,
)

pytestmark = pytest.mark.unit


def night(count, hr=56.0, hrv=55.0, movement=0.1):
    """`count` evenly spaced 5-minute samples. Defaults sit exactly on the baselines."""
    return [Sample(t=i * 5, hr=hr, hrv=hrv, movement=movement, temp=36.4) for i in range(count)]


# --- hand-calculated cases -------------------------------------------------------------------


def test_full_night_at_baseline():
    # 96 samples = 8 h asleep. HRV and resting HR on baseline -> both components 80, duration 100.
    metrics = compute_metrics(night(96))
    assert metrics.sleep_minutes == 480
    assert metrics.efficiency == 1.0
    assert metrics.avg_hrv == 55.0
    assert metrics.resting_hr == 56.0
    assert sleep_score(metrics) == 100
    assert readiness_score(metrics) == 86  # 0.4*80 + 0.3*80 + 0.3*100


def test_half_night_halves_the_duration_component():
    metrics = compute_metrics(night(48))
    assert metrics.sleep_minutes == 240
    assert sleep_score(metrics) == 65  # 0.7*50 + 0.3*100
    assert readiness_score(metrics) == 71  # 0.4*80 + 0.3*80 + 0.3*50


def test_restless_samples_lower_efficiency_and_duration():
    # every 4th sample is a movement spike: 72 of 96 samples asleep
    samples = [Sample(t=i * 5, hr=56, hrv=55, movement=0.9 if i % 4 == 0 else 0.1) for i in range(96)]
    metrics = compute_metrics(samples)
    assert metrics.sleep_minutes == 360
    assert metrics.efficiency == 0.75
    assert sleep_score(metrics) == 75  # 0.7*75 + 0.3*75


def test_v2_weights_hrv_more_heavily():
    metrics = compute_metrics(night(96, hrv=66.0))  # HRV 20% over baseline -> component 100
    assert readiness_score(metrics, "v1") == 94  # 0.4*100 + 0.3*80 + 0.3*100
    assert readiness_score(metrics, "v2") == 96  # 0.5*100 + 0.2*80 + 0.3*100


def test_missing_hrv_drops_that_component_and_renormalises():
    metrics = compute_metrics([s.model_copy(update={"hrv": None}) for s in night(96)])
    assert metrics.avg_hrv is None
    assert readiness_score(metrics) == 90  # (0.3*80 + 0.3*100) / 0.6


def test_missing_heart_rate_drops_that_component_and_renormalises():
    metrics = compute_metrics([s.model_copy(update={"hr": None}) for s in night(96)])
    assert metrics.resting_hr is None
    assert readiness_score(metrics) == 89  # (0.4*80 + 0.3*100) / 0.7 = 88.57


def test_resting_hr_is_the_mean_of_the_lowest_tenth():
    samples = [Sample(t=i * 5, hr=50.0 + i, hrv=55, movement=0.1) for i in range(20)]  # 50..69
    assert compute_metrics(samples).resting_hr == 50.5  # mean(50, 51)


def test_no_samples_gives_no_metrics():
    assert compute_metrics([]) is None


@pytest.mark.parametrize(
    "movement, asleep_minutes",
    [(ASLEEP_MOVEMENT - 0.01, 5), (ASLEEP_MOVEMENT, 0), (None, 0)],
)
def test_asleep_threshold_is_exclusive_and_unknown_movement_is_not_sleep(movement, asleep_minutes):
    sample = Sample(t=0, hr=56, hrv=55, movement=movement)
    assert compute_metrics([sample]).sleep_minutes == asleep_minutes


# --- properties ------------------------------------------------------------------------------


def optional(strategy):
    return st.one_of(st.none(), strategy)


samples_strategy = st.builds(
    Sample,
    t=st.integers(0, 2000),
    hr=optional(st.floats(20, 250)),
    hrv=optional(st.floats(0, 300)),
    movement=optional(st.floats(0, 1)),
    temp=optional(st.floats(25, 45)),
)
formulas = st.sampled_from(["v1", "v2"])


@settings(max_examples=300)
@given(st.lists(samples_strategy, min_size=1, max_size=200), formulas)
def test_scores_never_leave_0_to_100_for_any_input(samples, formula):
    metrics = compute_metrics(samples)
    assert 0.0 <= metrics.efficiency <= 1.0
    for score in (sleep_score(metrics), readiness_score(metrics, formula)):
        assert isinstance(score, int)
        assert 0 <= score <= 100


@settings(max_examples=300)
@given(
    st.integers(0, 1500),
    st.floats(0, 1),
    st.floats(30, 120),
    st.tuples(st.floats(0, 300), st.floats(0, 300)),
    formulas,
)
def test_higher_hrv_never_lowers_readiness(minutes, efficiency, rhr, hrv_pair, formula):
    low, high = sorted(hrv_pair)
    worse = NightMetrics(minutes, efficiency, low, rhr)
    better = NightMetrics(minutes, efficiency, high, rhr)
    assert readiness_score(worse, formula) <= readiness_score(better, formula)


@settings(max_examples=300)
@given(
    st.integers(0, 1500),
    st.floats(0, 1),
    st.floats(0, 300),
    st.tuples(st.floats(30, 120), st.floats(30, 120)),
    formulas,
)
def test_higher_resting_hr_never_raises_readiness(minutes, efficiency, hrv, rhr_pair, formula):
    low, high = sorted(rhr_pair)
    calmer = NightMetrics(minutes, efficiency, hrv, low)
    stressed = NightMetrics(minutes, efficiency, hrv, high)
    assert readiness_score(stressed, formula) <= readiness_score(calmer, formula)


@settings(max_examples=300)
@given(st.tuples(st.integers(0, 1500), st.integers(0, 1500)), st.floats(0, 1))
def test_more_sleep_never_lowers_sleep_score(minutes_pair, efficiency):
    low, high = sorted(minutes_pair)
    assert sleep_score(NightMetrics(low, efficiency, None, None)) <= sleep_score(
        NightMetrics(high, efficiency, None, None)
    )
