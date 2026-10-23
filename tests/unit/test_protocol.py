import pytest
from hypothesis import given
from hypothesis import strategies as st

from api.main import packet_problem
from api.models import Packet
from api.protocol import checksum as api_checksum
from ring_sim import PACKET_SIZE, RingSimulator, checksum as ring_checksum, load_night, make_packets

pytestmark = pytest.mark.unit

NIGHTS = ["good_night", "short_night", "restless_night", "missing_data"]
SAMPLE = {"t": 0, "hr": 55.0, "hrv": 50.0, "movement": 0.1, "temp": 36.4}


def packet(seq=0, samples=None, **overrides):
    samples = [SAMPLE] if samples is None else samples
    return Packet(**{"seq": seq, "samples": samples, "checksum": ring_checksum(samples), **overrides})


# --- ring and API must agree on the wire format ----------------------------------------------


@pytest.mark.parametrize("name", NIGHTS)
def test_ring_and_api_compute_the_same_checksum_for_every_packet(name):
    for p in RingSimulator(load_night(name)).packets():
        assert ring_checksum(p["samples"]) == api_checksum(p["samples"]) == p["checksum"]


def test_checksum_ignores_key_order_but_not_values():
    assert ring_checksum([{"t": 0, "hr": 55.0}]) == ring_checksum([{"hr": 55.0, "t": 0}])
    assert ring_checksum([{"t": 0, "hr": 55.0}]) != ring_checksum([{"t": 0, "hr": 55.1}])


# --- packetising ------------------------------------------------------------------------------


@pytest.mark.parametrize("name, expected_packets", [("good_night", 8), ("short_night", 5), ("missing_data", 7)])
def test_night_is_split_into_numbered_packets(name, expected_packets):
    packets = RingSimulator(load_night(name)).packets()
    assert [p["seq"] for p in packets] == list(range(expected_packets))
    assert all(len(p["samples"]) <= PACKET_SIZE for p in packets)


@given(st.lists(st.fixed_dictionaries({"t": st.integers(0, 10_000)}), max_size=100), st.integers(1, 20))
def test_packets_reassemble_into_the_original_samples(samples, size):
    packets = make_packets(samples, size)
    assert [s for p in packets for s in p["samples"]] == samples
    assert [p["seq"] for p in packets] == list(range(len(packets)))


# --- what the API rejects ---------------------------------------------------------------------


def test_valid_packet_has_no_problem():
    assert packet_problem(packet(), total_packets=1) is None


def test_bad_checksum_is_rejected():
    assert packet_problem(packet(checksum=1234), total_packets=1) == "bad_checksum"


def test_single_flipped_checksum_bit_is_rejected():
    good = packet()
    assert packet_problem(packet(checksum=good.checksum ^ 1), total_packets=1) == "bad_checksum"


def test_sequence_number_must_be_inside_the_announced_range():
    assert packet_problem(packet(seq=3), total_packets=3) == "seq_out_of_range"
    assert packet_problem(packet(seq=2), total_packets=3) is None


def test_empty_packet_is_rejected():
    assert packet_problem(packet(samples=[]), total_packets=1) == "empty_packet"


@pytest.mark.parametrize("bad", [{"hr": 900}, {"movement": 1.5}, {"t": -5}, {"hrv": "high"}])
def test_out_of_range_sample_values_are_rejected_even_with_a_correct_checksum(bad):
    assert packet_problem(packet(samples=[{**SAMPLE, **bad}]), total_packets=1) == "invalid_samples"


def test_range_is_checked_before_checksum():
    assert packet_problem(packet(seq=9, checksum=1), total_packets=3) == "seq_out_of_range"
