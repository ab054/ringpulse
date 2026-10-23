"""The fixtures the emulator tests rely on, checked without an emulator: a real API process,
a ring syncing to it over real HTTP, and a clean database for every test."""
import httpx
import pytest
from harness import API_URL

pytestmark = pytest.mark.api


def test_ring_syncs_to_a_live_api_over_http(api_server, ring_client, ring):
    simulator = ring("good_night")

    response = simulator.sync(ring_client)

    assert response.json()["sync_status"] == "complete"
    latest = ring_client.get("/nights/latest").json()
    assert latest["night_id"] == simulator.night_id
    assert latest["sleep_score"] is not None


def test_every_test_starts_with_an_empty_api(api_server, ring_client):
    assert ring_client.get("/nights/latest").status_code == 404


def test_stopping_the_server_makes_it_unreachable_and_stop_is_repeatable(api_server, ring_client):
    api_server.stop()
    api_server.stop()

    with pytest.raises(httpx.ConnectError):
        httpx.get(f"{API_URL}/health", timeout=2)
