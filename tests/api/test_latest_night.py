"""GET /nights/latest: what the app's Today screen shows."""
import pytest

from ring_sim import faults

pytestmark = pytest.mark.api


def test_no_nights_yet_is_404(client):
    assert client.get("/nights/latest").status_code == 404


def test_latest_is_the_night_that_was_just_synced(client, ring, insights):
    simulator = ring("good_night")
    simulator.sync(client)

    assert client.get("/nights/latest").json() == insights(simulator.night_id)


def test_latest_follows_the_most_recent_sync(client, ring, insights):
    ring("good_night").sync(client)
    restless = ring("restless_night")
    restless.sync(client)

    assert client.get("/nights/latest").json()["night_id"] == restless.night_id


def test_resyncing_an_older_night_makes_it_the_latest_again(client, ring):
    good = ring("good_night")
    good.sync(client, faults.drop_seqs(good.packets(), [7]))
    ring("restless_night").sync(client)

    good.sync(client, [p for p in good.packets() if p["seq"] == 7])  # the missing packet finally arrives

    latest = client.get("/nights/latest").json()
    assert latest["night_id"] == good.night_id
    assert latest["sync_status"] == "complete"


def test_latest_shows_a_partial_night_with_its_missing_packets(client, ring):
    simulator = ring("good_night")
    simulator.sync(client, faults.drop_seqs(simulator.packets(), [3, 5]))

    latest = client.get("/nights/latest").json()

    assert latest["sync_status"] == "partial"
    assert latest["missing_packets"] == [3, 5]


def test_a_night_whose_packets_were_all_rejected_is_still_the_latest(client, ring):
    simulator = ring("good_night")
    everything = [p["seq"] for p in simulator.packets()]
    simulator.sync(client, faults.corrupt(simulator.packets(), everything))

    latest = client.get("/nights/latest").json()

    assert latest["night_id"] == simulator.night_id
    assert latest["sleep_score"] is None


def test_ids_that_only_start_with_latest_still_go_to_the_id_route(client, ring):
    ring("good_night").sync(client)

    assert client.get("/nights/latest-but-not-really").status_code == 404
