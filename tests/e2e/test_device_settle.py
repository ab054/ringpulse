"""A slow emulator can cover the app with an 'isn't responding' dialog; the harness has to get past it."""
import pytest
from harness import APP_ID, NOT_RESPONDING_TITLE, WAIT_BUTTON, dismiss_not_responding_dialog, settle_device

pytestmark = pytest.mark.unit


class Button:
    def __init__(self):
        self.clicks = 0

    def click(self):
        self.clicks += 1


class FakeDevice:
    """Shows an ANR dialog first; once 'Wait' is pressed and the app is brought back, the Today screen appears."""

    def __init__(self, dialog=True, app_comes_back=True, broken=False):
        self.dialog, self.app_comes_back, self.broken = dialog, app_comes_back, broken
        self.wait_button, self.activated, self.today_visible = Button(), 0, not dialog

    def find_elements(self, by, value):
        if self.broken:
            raise RuntimeError("session is gone")
        if value == "today_title":
            return [object()] if self.today_visible else []
        if value == NOT_RESPONDING_TITLE:
            return [object()] if self.dialog else []
        if value == WAIT_BUTTON:
            return [self.wait_button] if self.dialog else []
        raise AssertionError(f"unexpected lookup {value!r}")

    def activate_app(self, app_id):
        assert app_id == APP_ID
        self.activated += 1
        self.dialog = False
        self.today_visible = self.app_comes_back


def settle(device, **kw):
    return settle_device(device, sleep=lambda s: None, clock=iter(range(0, 1000)).__next__, **kw)


def test_a_healthy_device_needs_nothing():
    device = FakeDevice(dialog=False)
    assert settle(device) == [] and device.activated == 0 and device.wait_button.clicks == 0


def test_a_not_responding_dialog_is_dismissed_with_wait_and_the_app_is_brought_back():
    device = FakeDevice()

    notes = settle(device)

    assert notes == ["dismissed a 'not responding' dialog"]
    assert device.wait_button.clicks == 1 and device.activated == 1 and device.today_visible


def test_when_the_screen_never_appears_it_gives_up_with_a_note_and_does_not_raise():
    notes = settle(FakeDevice(app_comes_back=False), timeout=5)
    assert "today_title still not visible after 5s" in notes[-1]


def test_a_dead_session_is_noted_not_raised():
    notes = settle(FakeDevice(broken=True), timeout=3)
    assert any("session is gone" in n for n in notes)


def test_the_dialog_is_ignored_when_there_is_no_wait_button():
    class NoButton(FakeDevice):
        def find_elements(self, by, value):
            return [] if value == WAIT_BUTTON else super().find_elements(by, value)
    assert dismiss_not_responding_dialog(NoButton()) is False
