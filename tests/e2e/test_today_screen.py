"""What the user sees on the phone: the real app on an Android emulator talking to the real API.

The API starts empty for every test and the app starts with clean data. The ring simulator plays the
ring: a test syncs a night to the API, then taps Sync now in the app and checks the screen."""
import pytest
from screens import TodayScreen

from ring_sim import faults

pytestmark = pytest.mark.e2e


@pytest.fixture
def today(driver):
    return TodayScreen(driver).wait_until_loaded()


def test_before_any_sync_the_screen_says_there_is_no_night_yet(today):
    today.wait_for_badge("No night yet")

    assert today.sleep_score() == "--"
    assert today.readiness_score() == "--"
    assert today.night_id() is None
    assert today.error_message() is None
    assert today.sync_button_enabled()


@pytest.mark.parametrize("night", ["good_night", "restless_night"])
def test_sync_now_shows_the_scores_of_the_synced_night(today, ring, ring_client, night):
    simulator = ring(night)
    expected = simulator.night["expected"]
    simulator.sync(ring_client)

    today.tap_sync_now()
    today.wait_for_badge("Synced")

    assert today.night_id() == simulator.night_id
    assert int(today.sleep_score()) == pytest.approx(expected["sleep_score"], abs=expected["tolerance"])
    assert int(today.readiness_score()) == pytest.approx(expected["readiness_score"], abs=expected["tolerance"])


def test_lost_packets_show_a_partial_sync_badge(today, ring, ring_client):
    simulator = ring("good_night")
    simulator.sync(ring_client, faults.drop_seqs(simulator.packets(), [3, 5]))

    today.tap_sync_now()
    today.wait_for_badge("Partial sync (2 missing)")

    assert today.night_id() == simulator.night_id
    assert today.sleep_score() != "--"  # a partial night still gets scores from what arrived


def test_missing_packets_arriving_later_complete_the_night(today, ring, ring_client):
    simulator = ring("good_night")
    expected = simulator.night["expected"]
    simulator.sync(ring_client, faults.drop_seqs(simulator.packets(), [3, 5]))
    today.tap_sync_now()
    today.wait_for_badge("Partial sync (2 missing)")

    simulator.sync(ring_client, [p for p in simulator.packets() if p["seq"] in (3, 5)])  # the ring reconnects
    today.tap_sync_now()
    today.wait_for_badge("Synced")

    assert int(today.sleep_score()) == pytest.approx(expected["sleep_score"], abs=expected["tolerance"])
    assert int(today.readiness_score()) == pytest.approx(expected["readiness_score"], abs=expected["tolerance"])


def test_when_the_api_goes_away_the_app_says_so_and_keeps_the_last_scores(today, ring, ring_client, api_server):
    simulator = ring("good_night")
    simulator.sync(ring_client)
    today.tap_sync_now()
    today.wait_for_badge("Synced")
    scores_before = (today.sleep_score(), today.readiness_score())

    api_server.stop()
    today.tap_sync_now()
    today.wait_for_badge("Sync failed")

    assert "Can't reach the server" in today.error_message()
    assert "retry" in today.error_message()
    assert (today.sleep_score(), today.readiness_score()) == scores_before
    assert today.sync_button_enabled()  # the user can try again
