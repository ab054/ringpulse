"""Page objects: how the tests talk to the app. Elements are found by accessibility id, never by XPath,
so the tests survive layout changes. The ids are listed in docs/android-app.md."""
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait

SYNCING = "Syncing..."


class TodayScreen:
    def __init__(self, driver, timeout: float = 10, poll: float = 0.25):
        self.driver = driver
        self.timeout = timeout
        self.poll = poll

    # --- reading the screen ---

    def sleep_score(self) -> str:
        return self._text("sleep_score")

    def readiness_score(self) -> str:
        return self._text("readiness_score")

    def sync_badge(self) -> str:
        return self._text("sync_badge")

    def night_id(self) -> str | None:
        """The id of the night on screen, or None when no night is loaded."""
        return self._text("night_id") if self.is_present("night_id") else None

    def error_message(self) -> str | None:
        """Why the last sync failed, or None when there is no error."""
        return self._text("error_message") if self.is_present("error_message") else None

    def is_present(self, element_id: str) -> bool:
        return len(self.driver.find_elements(AppiumBy.ACCESSIBILITY_ID, element_id)) > 0

    def sync_button_enabled(self) -> bool:
        return self._wait().until(lambda d: d.find_element(AppiumBy.ACCESSIBILITY_ID, "sync_button")).is_enabled()

    # --- acting ---

    def tap_sync_now(self) -> None:
        button = self._wait().until(lambda d: d.find_element(AppiumBy.ACCESSIBILITY_ID, "sync_button"))
        button.click()

    # --- waiting ---

    def wait_until_loaded(self) -> "TodayScreen":
        """The screen is up and the automatic sync it does on opening has finished."""
        self._wait().until(lambda d: d.find_element(AppiumBy.ACCESSIBILITY_ID, "today_title"))
        self._wait().until(lambda d: self.sync_badge() != SYNCING)
        return self

    def wait_for_badge(self, expected: str) -> None:
        """Wait for the sync badge to read `expected`. On timeout, fails saying what it showed instead.

        Wait for the state you expect, not for "syncing to finish": right after a tap the old badge can
        still be on screen, and "finished" would be true for the stale state."""
        last_seen = []

        def matches(_driver):
            last_seen[:] = [self.sync_badge()]
            return last_seen[0] == expected

        try:
            self._wait().until(matches)
        except TimeoutException:
            raise AssertionError(
                f"Sync badge never read {expected!r} within {self.timeout}s; last seen: {last_seen or 'nothing'}"
            ) from None

    # --- internals ---

    def _wait(self) -> WebDriverWait:
        return WebDriverWait(self.driver, self.timeout, poll_frequency=self.poll)

    def _text(self, element_id: str) -> str:
        element = self._wait().until(lambda d: d.find_element(AppiumBy.ACCESSIBILITY_ID, element_id))
        return element.text
