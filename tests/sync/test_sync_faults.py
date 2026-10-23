"""The ring -> API path under bad conditions, driven by the ring simulator's faults."""
import pytest

from ring_sim import faults

pytestmark = pytest.mark.sync

NIGHTS = ["good_night", "short_night", "restless_night", "missing_data"]


@pytest.mark.parametrize("seed", range(5))
def test_random_packet_loss_is_reported_exactly_and_never_crashes(client, ring, insights, seed):
    simulator = ring("good_night")
    packets = simulator.packets()
    delivered = faults.drop_rate(packets, rate=0.25, seed=seed)
    lost = sorted({p["seq"] for p in packets} - {p["seq"] for p in delivered})

    body = simulator.sync(client, delivered).json()
    got = insights(simulator.night_id)

    assert body["missing_packets"] == lost
    assert body["sync_status"] == ("partial" if lost else "complete")
    if delivered:
        assert 0 <= got["sleep_score"] <= 100
        assert 0 <= got["readiness_score"] <= 100
    else:
        assert got["sleep_score"] is None


def test_partial_sync_never_claims_more_sleep_than_the_full_night(make_client, ring):
    simulator = ring("good_night")
    partial, full = make_client(), make_client()

    simulator.sync(partial, faults.drop_seqs(simulator.packets(), [1, 4]))
    simulator.sync(full)

    assert (
        partial.get(f"/nights/{simulator.night_id}").json()["sleep_minutes"]
        < full.get(f"/nights/{simulator.night_id}").json()["sleep_minutes"]
    )


def test_disconnect_mid_sync_then_reconnect_completes_the_night(make_client, ring):
    simulator = ring("good_night")
    packets = simulator.packets()
    flaky, reference = make_client(), make_client()
    simulator.sync(reference)

    first = simulator.sync(flaky, faults.disconnect_after(packets, 4)).json()
    assert first["sync_status"] == "partial"
    assert first["missing_packets"] == [4, 5, 6, 7]

    second = simulator.sync(flaky, packets[4:]).json()  # the ring still holds the unsent packets
    assert second["accepted"] == 4
    assert second["sync_status"] == "complete"
    night_id = simulator.night_id
    assert flaky.get(f"/nights/{night_id}").json() == reference.get(f"/nights/{night_id}").json()


def test_full_retransmit_after_a_loss_fills_the_gap_and_ignores_the_rest(client, ring):
    simulator = ring("good_night")
    simulator.sync(client, faults.drop_seqs(simulator.packets(), [3]))

    body = simulator.sync(client).json()

    assert (body["accepted"], body["duplicates"]) == (1, 7)
    assert body["sync_status"] == "complete"


def test_corrupted_packet_is_rejected_then_accepted_when_resent_clean(client, ring):
    simulator = ring("good_night")
    packets = simulator.packets()

    first = simulator.sync(client, faults.corrupt(packets, [2])).json()
    assert first["rejected"] == [{"seq": 2, "reason": "bad_checksum"}]
    assert first["missing_packets"] == [2]

    second = simulator.sync(client, [packets[2]]).json()
    assert second["sync_status"] == "complete"


def test_duplicated_packets_are_counted_once(make_client, ring):
    simulator = ring("good_night")
    noisy, clean = make_client(), make_client()

    body = simulator.sync(noisy, faults.duplicate(simulator.packets(), [0, 1, 2])).json()
    simulator.sync(clean)

    assert (body["accepted"], body["duplicates"]) == (8, 3)
    night_id = simulator.night_id
    assert noisy.get(f"/nights/{night_id}").json() == clean.get(f"/nights/{night_id}").json()


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("name", NIGHTS)
def test_whatever_goes_wrong_a_clean_retry_converges_to_the_same_night(make_client, ring, name, seed):
    """Loss, corruption, duplicates and reordering in one bad sync, then a clean one."""
    simulator = ring(name)
    chaotic, reference = make_client(), make_client()
    simulator.sync(reference)

    bad_sync = faults.reorder(
        faults.duplicate(faults.corrupt(faults.drop_rate(simulator.packets(), 0.3, seed=seed), [0, 1]), [2, 3]),
        seed=seed,
    )
    simulator.sync(chaotic, bad_sync)
    simulator.sync(chaotic)  # the ring tries again with everything

    night_id = simulator.night_id
    assert chaotic.get(f"/nights/{night_id}").json() == reference.get(f"/nights/{night_id}").json()
