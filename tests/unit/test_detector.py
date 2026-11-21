"""The code around the model: feature extraction, loading, scoring. Ordinary deterministic tests.

The model's *quality* is not asserted here; that lives in tests/data/test_model_gate.py.
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ai.detector import LABEL, Detection, detect, load_model, score
from ai.features import BASELINE_RHR, Features, extract

pytestmark = pytest.mark.unit


def night(hr=56.0, hrv=55.0, temp=36.15, movement=0.05, n=20):
    return [{"t": i * 5, "hr": hr, "hrv": hrv, "temp": temp, "movement": movement} for i in range(n)]


def test_features_of_a_baseline_night_are_zero():
    f = extract(night())

    assert f.rhr_delta == pytest.approx(0)
    assert f.hrv_drop == pytest.approx(0)
    assert f.temp_delta == pytest.approx(0)
    assert f.restless_share == 0


def test_resting_hr_uses_the_lowest_tenth_of_readings():
    samples = night(hr=70.0, n=18) + night(hr=50.0, n=2)

    assert extract(samples).rhr_delta == pytest.approx(50.0 - BASELINE_RHR)


def test_a_dead_hrv_sensor_gives_no_hrv_feature_instead_of_zero():
    assert extract(night(hrv=None)).hrv_drop is None


def test_a_night_without_heart_rate_is_not_judged():
    assert extract(night(hr=None)) is None
    assert detect(night(hr=None), "v1") is None


def test_unknown_model_version_names_the_known_ones():
    with pytest.raises(ValueError, match="v1"):
        load_model("v99")


def test_missing_hrv_is_filled_with_the_models_imputed_value():
    model = {"bias": 0.0, "threshold": 0.5, "impute": {"hrv_drop": 0.5, "temp_delta": 0.0},
             "weights": {"rhr_delta": 0.0, "hrv_drop": 2.0, "temp_delta": 0.0, "restless_share": 0.0}}
    missing = Features(rhr_delta=0, hrv_drop=None, temp_delta=0, restless_share=0)
    present = Features(rhr_delta=0, hrv_drop=0.5, temp_delta=0, restless_share=0)

    assert score(missing, model) == score(present, model)


def test_detection_carries_label_confidence_and_version():
    sick = night(hr=64.0, hrv=35.0, temp=37.0)

    d = detect(sick, "v1")

    assert d == Detection(label=LABEL, confidence=d.confidence, model_version="v1")
    assert d.confidence > 0.9


def test_a_healthy_night_is_not_flagged():
    assert detect(night(), "v1").label is None


@settings(max_examples=200, deadline=None)
@given(hr=st.floats(30, 120), hrv=st.one_of(st.none(), st.floats(5, 150)),
       temp=st.floats(34, 40), movement=st.floats(0, 1))
def test_confidence_is_always_a_probability(hr, hrv, temp, movement):
    for version in ("v1", "v2", "v3"):
        d = detect(night(hr=hr, hrv=hrv, temp=temp, movement=movement), version)
        assert 0.0 <= d.confidence <= 1.0


@settings(max_examples=100, deadline=None)
@given(base=st.floats(50, 65), bump=st.floats(0.5, 10))
def test_higher_resting_hr_never_lowers_confidence(base, bump):
    # A metamorphic property: no labels needed, only how the output must move when the input moves.
    low = detect(night(hr=base), "v1").confidence
    high = detect(night(hr=base + bump), "v1").confidence
    assert high >= low
