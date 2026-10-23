"""The page object against a fake driver: checks how it finds and waits, with no emulator needed."""
import pytest

pytest.importorskip("appium", reason="Appium client not installed: pip install -r requirements-dev.txt")

from appium.webdriver.common.appiumby import AppiumBy  # noqa: E402
from screens import TodayScreen  # noqa: E402
from selenium.common.exceptions import NoSuchElementException  # noqa: E402

pytestmark = pytest.mark.unit


class FakeElement:
    def __init__(self, text="", enabled=True):
        self.text = text
        self._enabled = enabled
        self.clicks = 0

    def is_enabled(self):
        return self._enabled

    def click(self):
        self.clicks += 1


class FakeDriver:
    """Looks elements up by accessibility id only, like the app's ids; anything else is a test bug."""

    def __init__(self, elements):
        self.elements = elements
        self.lookups = []

    def find_element(self, by, value):
        assert by == AppiumBy.ACCESSIBILITY_ID, f"page object must not locate by {by!r}"
        self.lookups.append(value)
        if value not in self.elements:
            raise NoSuchElementException(value)
        return self.elements[value]

    def find_elements(self, by, value):
        assert by == AppiumBy.ACCESSIBILITY_ID
        return [self.elements[value]] if value in self.elements else []


def screen(**elements):
    return TodayScreen(FakeDriver(elements), timeout=0.3, poll=0.01)


def test_reads_values_by_accessibility_id():
    today = screen(sleep_score=FakeElement("97"), readiness_score=FakeElement("93"), sync_badge=FakeElement("Synced"))

    assert (today.sleep_score(), today.readiness_score(), today.sync_badge()) == ("97", "93", "Synced")
    assert today.driver.lookups == ["sleep_score", "readiness_score", "sync_badge"]


def test_optional_elements_are_none_when_absent_and_text_when_present():
    assert screen().night_id() is None
    assert screen().error_message() is None
    assert screen(night_id=FakeElement("night-good-night")).night_id() == "night-good-night"


def test_tap_sync_now_clicks_the_button():
    button = FakeElement("Sync now")

    screen(sync_button=button).tap_sync_now()

    assert button.clicks == 1


class ChangingElement:
    """An element whose text changes each time it is read, like a badge that updates while polled."""

    def __init__(self, *texts):
        self._texts = list(texts)

    @property
    def text(self):
        return self._texts.pop(0) if len(self._texts) > 1 else self._texts[0]


def test_wait_for_badge_returns_once_the_badge_changes():
    today = screen(sync_badge=ChangingElement("Syncing...", "Syncing...", "Synced"))

    today.wait_for_badge("Synced")  # does not raise


def test_wait_for_badge_failure_says_what_was_on_screen():
    today = screen(sync_badge=FakeElement("Sync failed"))

    with pytest.raises(AssertionError, match=r"never read 'Synced'.*last seen: \['Sync failed'\]"):
        today.wait_for_badge("Synced")


def test_wait_until_loaded_waits_for_the_title_and_for_syncing_to_end():
    today = screen(today_title=FakeElement("Today"), sync_badge=FakeElement("No night yet"))

    assert today.wait_until_loaded() is today
