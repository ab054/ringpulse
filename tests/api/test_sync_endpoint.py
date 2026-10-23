import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from ring_sim import checksum, faults

pytestmark = pytest.mark.api


def test_clean_sync_reports_everything_accepted(client, ring):
    body = ring("good_night").sync(client).json()

    assert body["accepted"] == 8
    assert body["duplicates"] == 0
    assert body["rejected"] == []
    assert body["sync_status"] == "complete"
    assert (body["received_packets"], body["total_packets"], body["missing_packets"]) == (8, 8, [])


def test_syncing_the_same_night_twice_changes_nothing(client, ring, insights):
    simulator = ring("good_night")
    simulator.sync(client)
    before = insights(simulator.night_id)

    second = simulator.sync(client).json()

    assert (second["accepted"], second["duplicates"]) == (0, 8)
    assert second["sync_status"] == "complete"
    assert insights(simulator.night_id) == before


def test_out_of_order_packets_rebuild_the_same_night(make_client, ring):
    simulator = ring("good_night")
    in_order, shuffled = make_client(), make_client()

    simulator.sync(in_order)
    simulator.sync(shuffled, faults.reorder(simulator.packets(), seed=7))

    assert shuffled.get(f"/nights/{simulator.night_id}").json() == in_order.get(f"/nights/{simulator.night_id}").json()


def test_a_gap_makes_the_night_partial_and_names_the_missing_packets(client, ring):
    simulator = ring("good_night")

    body = simulator.sync(client, faults.drop_seqs(simulator.packets(), [3, 5])).json()

    assert body["sync_status"] == "partial"
    assert body["missing_packets"] == [3, 5]
    assert body["received_packets"] == 6


def test_missing_packets_can_arrive_in_a_later_sync(client, ring):
    simulator = ring("good_night")
    simulator.sync(client, faults.drop_seqs(simulator.packets(), [3]))

    body = simulator.sync(client, [p for p in simulator.packets() if p["seq"] == 3]).json()

    assert body["accepted"] == 1
    assert body["sync_status"] == "complete"


def test_packet_with_bad_checksum_is_rejected_and_not_stored(client, ring):
    simulator = ring("good_night")

    body = simulator.sync(client, faults.corrupt(simulator.packets(), [2])).json()

    assert body["rejected"] == [{"seq": 2, "reason": "bad_checksum"}]
    assert body["missing_packets"] == [2]
    assert body["sync_status"] == "partial"


def test_sequence_number_beyond_the_announced_total_is_rejected(client, ring):
    simulator = ring("good_night")
    stray = {**simulator.packets()[0], "seq": 99}

    body = simulator.sync(client, simulator.packets() + [stray]).json()

    assert body["rejected"] == [{"seq": 99, "reason": "seq_out_of_range"}]
    assert body["sync_status"] == "complete"


def test_packet_with_impossible_values_is_rejected_even_if_its_checksum_is_right(client):
    samples = [{"t": 0, "hr": 900.0, "hrv": 50.0, "movement": 0.1, "temp": 36.4}]
    request = {
        "device_id": "ring-1",
        "night_id": "n1",
        "total_packets": 1,
        "packets": [{"seq": 0, "samples": samples, "checksum": checksum(samples)}],
    }

    body = client.post("/sync", json=request).json()

    assert body["rejected"] == [{"seq": 0, "reason": "invalid_samples"}]


def test_a_packet_resent_with_different_content_is_rejected_and_the_first_copy_wins(client, ring, insights):
    simulator = ring("good_night")
    simulator.sync(client)
    before = insights(simulator.night_id)
    altered = [{**s, "hr": s["hr"] + 1} for s in simulator.packets()[0]["samples"]]

    body = simulator.sync(client, [{"seq": 0, "samples": altered, "checksum": checksum(altered)}]).json()

    assert body["rejected"] == [{"seq": 0, "reason": "conflicting_duplicate"}]
    assert insights(simulator.night_id) == before


def test_a_night_where_every_packet_was_rejected_has_no_scores(client, ring, insights):
    simulator = ring("good_night")
    everything = [p["seq"] for p in simulator.packets()]

    simulator.sync(client, faults.corrupt(simulator.packets(), everything))
    got = insights(simulator.night_id)

    assert got["sync_status"] == "partial"
    assert got["received_packets"] == 0
    assert (got["sleep_minutes"], got["sleep_score"], got["readiness_score"]) == (None, None, None)


def test_same_night_id_from_another_device_is_a_conflict(client, ring):
    simulator = ring("good_night")
    simulator.sync(client)
    request = {"device_id": "some-other-ring", "night_id": simulator.night_id, "total_packets": 8, "packets": []}

    assert client.post("/sync", json=request).status_code == 409


def test_changing_the_packet_total_of_a_known_night_is_a_conflict(client, ring):
    simulator = ring("good_night")
    simulator.sync(client)
    request = {"device_id": simulator.device_id, "night_id": simulator.night_id, "total_packets": 9, "packets": []}

    assert client.post("/sync", json=request).status_code == 409


def test_unknown_night_is_404(client):
    assert client.get("/nights/does-not-exist").status_code == 404


@pytest.mark.parametrize(
    "request_body",
    [
        {"night_id": "n1", "total_packets": 1, "packets": []},  # no device_id
        {"device_id": "d", "night_id": "n1", "total_packets": 0, "packets": []},  # zero packets
        {"device_id": "", "night_id": "n1", "total_packets": 1, "packets": []},  # empty device_id
        {"device_id": "d", "night_id": "n1", "total_packets": 1, "packets": "none"},  # wrong type
    ],
    ids=["missing-field", "zero-total", "empty-device", "wrong-type"],
)
def test_malformed_requests_are_422(client, request_body):
    assert client.post("/sync", json=request_body).status_code == 422


def test_nights_do_not_leak_into_each_other(make_client, ring):
    shared, good_only = make_client(), make_client()
    ring("good_night").sync(good_only)

    ring("good_night").sync(shared)
    ring("restless_night").sync(shared)

    night_id = ring("good_night").night_id
    assert shared.get(f"/nights/{night_id}").json() == good_only.get(f"/nights/{night_id}").json()


def test_a_synced_night_survives_an_api_restart(tmp_path, ring):
    path = str(tmp_path / "restart.db")
    simulator = ring("good_night")
    simulator.sync(TestClient(create_app(path)))

    after_restart = TestClient(create_app(path)).get(f"/nights/{simulator.night_id}").json()

    assert after_restart["sync_status"] == "complete"
    assert after_restart["sleep_score"] is not None
