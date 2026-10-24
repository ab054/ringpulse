# Emulator tests (Appium)

These tests drive the real app on an Android emulator against the real API, and check what the user sees. They live in `tests/e2e/` and carry the `e2e` marker.

## What runs where

```
pytest ──▶ ring simulator ──sync──▶ API (uvicorn, started by the tests, empty database per test)
   │                                   ▲
   └──▶ Appium server ──▶ emulator ──▶ app ── GET /nights/latest (10.0.2.2:8000)
```

- The tests start and stop the API themselves, on port 8000 (the app is built to call that port). Stop any API you started by hand first, or the tests fail with a message saying so.
- Every test gets a fresh app install and an empty API, so no test sees another's data.
- Elements are found by accessibility id through the `TodayScreen` page object in `tests/e2e/screens.py`. Waits are explicit; there are no sleeps.

## Before each run

```bash
# 1. an emulator is running; this must list a device
adb devices

# 2. in one terminal: the Appium server
appium

# 3. in another terminal (virtual environment active), build the app if it changed, then run
./gradlew assembleDebug
pytest -m e2e
```

One-time setup is Node.js, `npm install -g appium`, `appium driver install uiautomator2`, and `ANDROID_HOME` / `JAVA_HOME` set (see [android-app.md](android-app.md)).

Plain `pytest` also works: without an Appium server or APK the emulator tests are skipped with the reason shown, and everything else runs.

## What the tests check

| Test | Checks |
|---|---|
| Before any sync | `No night yet`, scores `--`, no night id, no error, Sync now enabled |
| Sync now (good and restless nights) | Night id and both scores match the golden values within tolerance, badge `Synced` |
| Lost packets | Badge `Partial sync (2 missing)`, scores still shown |
| Missing packets arrive later | After a second tap the night is `Synced` with the golden scores |
| API goes away | `Sync failed`, error message with a retry hint, last scores kept, button usable |

## When a test fails

The evidence is saved to `artifacts/e2e/<test name>/` (git-ignored):

| File | Use it to |
|---|---|
| `screenshot.png` | see what was on screen |
| `page_source.xml` | see the element tree: ids, texts, enabled state. The first place to look when an element is not found |
| `logcat.txt` | read the app's log, including crashes |

A `*.error.txt` file next to them means that piece could not be captured (for example the session had died).

## System dialogs on a slow emulator

CI emulators are slow at start, and Android may then put an "isn't responding" dialog (an ANR, for example "Pixel Launcher isn't responding") on top of the app. Appium cannot see the app behind it, so the Today screen looks missing and every test fails in setup. This was the cause of the CI failures seen so far (found from the saved emulator screenshot).

Before each test the `driver` fixture calls `settle_device` (`harness.py`): if the Today screen is not visible it presses **Wait** on such a dialog and brings the app back to the front, for up to 30 seconds, and prints what it had to do (`[e2e] device needed help ...`). It never fails a test itself. CI also uses the lighter `default` Android image instead of `google_apis`, which does not need Google services.

If it happens often, that line in the log is the measure: it counts how often the emulator needed help.

## Settings

| Environment variable | Default | Meaning |
|---|---|---|
| `APPIUM_URL` | `http://127.0.0.1:4723` | where the Appium server listens |
| `RINGPULSE_APK` | `app/build/outputs/apk/debug/app-debug.apk` | the app to install |
| `ANDROID_SERIAL` | (any connected device) | which device when several are connected |
| `E2E_REQUIRED` | unset | set to `1` in CI: missing setup fails instead of skipping |
