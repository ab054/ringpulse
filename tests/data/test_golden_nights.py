import pytest

pytestmark = pytest.mark.data

NIGHTS = ["good_night", "short_night", "restless_night", "missing_data"]
SCORES = ("sleep_score", "readiness_score")


@pytest.mark.parametrize("name", NIGHTS)
def test_scores_match_the_golden_night_within_tolerance(client, ring, insights, name):
    simulator = ring(name)
    expected = simulator.night["expected"]
    simulator.sync(client)

    got = insights(simulator.night_id)

    for score in SCORES:
        assert got[score] == pytest.approx(expected[score], abs=expected["tolerance"]), score


def test_nights_rank_the_way_a_person_would_expect(client, ring, insights):
    results = {}
    for name in NIGHTS:
        simulator = ring(name)
        simulator.sync(client)
        results[name] = insights(simulator.night_id)

    assert results["good_night"]["sleep_score"] == max(r["sleep_score"] for r in results.values())
    assert results["good_night"]["readiness_score"] == max(r["readiness_score"] for r in results.values())
    assert results["restless_night"]["sleep_score"] == min(r["sleep_score"] for r in results.values())
    assert results["restless_night"]["readiness_score"] == min(r["readiness_score"] for r in results.values())
    assert results["short_night"]["sleep_minutes"] < results["good_night"]["sleep_minutes"]


def test_night_with_recording_gaps_and_hrv_dropout_still_gets_scores(client, ring, insights):
    simulator = ring("missing_data")
    simulator.sync(client)

    got = insights(simulator.night_id)

    assert got["sync_status"] == "complete"  # gaps in the recording are not gaps in the sync
    assert got["sleep_score"] is not None
    assert got["readiness_score"] is not None


@pytest.mark.parametrize("name", NIGHTS)
def test_new_readiness_formula_stays_within_5_points_of_the_old_one(client, ring, insights, monkeypatch, name):
    simulator = ring(name)
    simulator.sync(client)

    monkeypatch.setenv("RINGPULSE_READINESS_FORMULA", "v1")
    old = insights(simulator.night_id)
    monkeypatch.setenv("RINGPULSE_READINESS_FORMULA", "v2")
    new = insights(simulator.night_id)

    assert (old["readiness_formula"], new["readiness_formula"]) == ("v1", "v2")
    assert abs(new["readiness_score"] - old["readiness_score"]) <= 5
    assert new["sleep_score"] == old["sleep_score"]  # the flag only touches readiness
