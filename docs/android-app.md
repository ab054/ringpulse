# Android app (Today screen)

A deliberately small app: the device layer and the tests are the point, the UI is a stock Android Studio template with one screen.

The Today screen shows the latest synced night from `GET /nights/latest`: a sleep score, a readiness score, a sync badge and a **Sync now** button. It fetches once when it opens and again on every tap of the button.

## Screen states

| Situation | Scores | Badge | Extra |
|---|---|---|---|
| Opened, request in flight | last known or `--` | `Syncing...` | button disabled |
| Night fully synced | both scores | `Synced` | night id shown |
| Some packets missing | scores from what arrived | `Partial sync (N missing)` | night id shown |
| API has no nights yet | `--` | `No night yet` | |
| API unreachable or error | last known or `--` | `Sync failed` | error message with a retry hint |

## Accessibility ids (for Appium)

Every element's content description equals its test tag, so tests find it by accessibility id, never by XPath. The displayed value is the element's text.

| Id | Shows |
|---|---|
| `today_title` | the screen title |
| `sleep_score` | sleep score, or `--` |
| `readiness_score` | readiness score, or `--` |
| `sync_badge` | the badge text from the table above |
| `night_id` | id of the night on screen (only when one is loaded) |
| `error_message` | why the last sync failed (only after a failure) |
| `sync_button` | the Sync now button |

## One-time setup

1. **Create the project.** Android Studio → New Project → *Empty Activity* (the Jetpack Compose one). Name `RingPulse`, package name `com.ringpulse.app`, minimum SDK API 26, build configuration language Kotlin DSL. Keep the default save location for now.
2. **Add the sources.** Copy the three files from `android-sources/` into `app/src/main/java/com/ringpulse/app/` inside the new project, replacing the generated `MainActivity.kt`. The generated `ui/theme` folder can stay unused.
3. **Allow the app to reach the local API.** In `app/src/main/AndroidManifest.xml` add the permission just above `<application>` and the `usesCleartextTraffic` attribute on `<application>` (the test API speaks plain HTTP):

   ```xml
   <uses-permission android:name="android.permission.INTERNET" />

   <application
       android:usesCleartextTraffic="true"
       ...the attributes that are already there...>
   ```
4. **Create an emulator.** Device Manager → Create device → a Pixel phone, system image API 34 or 35 (pick the one that matches your processor).

## Try it by hand

The emulator reaches your computer at `10.0.2.2`, which is where the app looks for the API.

```bash
# terminal 1: the API
docker compose up --build            # or: uvicorn api.main:create_app --factory

# terminal 2: play the ring
python -m ring_sim sync good_night
```

Run the app and press **Sync now**.

| Do this | Expect on screen |
|---|---|
| `python -m ring_sim sync good_night` | Sleep 97, Readiness 93, `Synced`, `night-good-night` |
| `python -m ring_sim sync restless_night` | Sleep 60, Readiness 58, `Synced` |
| `python -m ring_sim sync good_night --drop 3,5` (fresh API) | `Partial sync (2 missing)` |
| Stop the API, press Sync now | `Sync failed` and an error message; last scores stay |
| Fresh API with no syncs | `No night yet` |

## Building from the repo

The repository root is the Gradle project and `app/` is the module, so no Android Studio is needed to build:

```bash
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"   # macOS; any JDK 17+ works
export ANDROID_HOME="$HOME/Library/Android/sdk"
./gradlew assembleDebug
# -> app/build/outputs/apk/debug/app-debug.apk   (the file Appium installs)
```

The first build downloads Gradle and the JDK the project asks for (`gradle/gradle-daemon-jvm.properties`), so it needs internet and takes a few minutes.
