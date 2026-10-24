"""Fixtures for tests that drive the real app on an Android emulator.

What they need running (docs/e2e-tests.md has the steps):
  - an Android emulator (or device) that `adb devices` lists
  - an Appium server (`appium`), default http://127.0.0.1:4723
  - the debug APK (`./gradlew assembleDebug`)
The API is started by the `api_server` fixture, not by hand.
"""
import os

import httpx
import pytest
from harness import API_URL, APK_PATH, APPIUM_URL, ApiServer, save_failure_artifacts, settle_device, failed_in_test

from ring_sim import RingSimulator, load_night


@pytest.fixture
def api_server(tmp_path):
    server = ApiServer(tmp_path / "e2e.db", tmp_path / "api.log")
    server.start()
    yield server
    server.stop()


@pytest.fixture
def ring_client(api_server):
    """An HTTP client the ring simulator uses to sync to the live API."""
    with httpx.Client(base_url=API_URL, timeout=10) as client:
        yield client


@pytest.fixture
def ring():
    """Factory: ring('good_night') -> a simulator holding that fixture night."""
    return lambda name: RingSimulator(load_night(name))


def unavailable(reason: str):
    """Skip when the emulator setup is missing, unless CI says e2e is required (then it is a failure)."""
    if os.environ.get("E2E_REQUIRED"):
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture(scope="session")
def appium_ready():
    try:
        httpx.get(f"{APPIUM_URL}/status", timeout=3).raise_for_status()
    except httpx.HTTPError:
        unavailable(f"No Appium server at {APPIUM_URL}. Start one with `appium`.")
    if not APK_PATH.exists():
        unavailable(f"No debug APK at {APK_PATH}. Build it with `./gradlew assembleDebug`.")


@pytest.fixture
def driver(request, appium_ready, api_server):
    """A fresh app session per test: the app is reinstalled with clean data, so no test sees another's state."""
    pytest.importorskip("appium")
    from appium import webdriver
    from appium.options.android import UiAutomator2Options

    options = UiAutomator2Options()
    options.platform_name = "Android"
    options.app = str(APK_PATH)
    options.no_reset = False
    options.new_command_timeout = 120
    options.auto_grant_permissions = True
    if os.environ.get("ANDROID_SERIAL"):
        options.udid = os.environ["ANDROID_SERIAL"]

    session = webdriver.Remote(APPIUM_URL, options=options)
    session.implicitly_wait(0)  # explicit waits only, so a missing element fails fast and clearly
    notes = settle_device(session)
    if notes:
        print(f"[e2e] device needed help before {request.node.name}: {'; '.join(notes)}")
    yield session

    if failed_in_test(request.node):
        save_failure_artifacts(session, request.node.name)
    session.quit()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Remember each phase's result on the test item, so the driver fixture can see if the test failed."""
    outcome = yield
    setattr(item, f"rep_{outcome.get_result().when}", outcome.get_result())
