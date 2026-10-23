import pytest

NIGHTS = ["good_night", "short_night", "restless_night", "missing_data"]


@pytest.mark.api
def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.api
@pytest.mark.parametrize("name", NIGHTS)
def test_clean_sync_completes_and_scores_are_in_range(client, ring, name):
    simulator = ring(name)

    response = simulator.sync(client)
    assert response.status_code == 200
    assert response.json()["sync_status"] == "complete"

    insights = client.get(f"/nights/{simulator.night_id}").json()
    assert insights["sync_status"] == "complete"
    assert 0 <= insights["sleep_score"] <= 100
    assert 0 <= insights["readiness_score"] <= 100
