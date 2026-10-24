#!/usr/bin/env bash
# Runs inside the emulator (android-emulator-runner calls this once the emulator has booted).
# Starts the Appium server, waits until it answers, then runs the emulator tests.
set -euo pipefail

mkdir -p artifacts/e2e
appium --log-level warn > artifacts/e2e/appium.log 2>&1 &
APPIUM_PID=$!

# When the run fails, keep what the emulator itself looked like. Appium's per-test evidence is lost if the
# session died, and in CI most failures so far were "the whole emulator or app is unhealthy".
collect_emulator_state() {
  status=$?
  if [ $status -ne 0 ]; then
    adb exec-out screencap -p > artifacts/e2e/emulator-screen.png 2>/dev/null || true
    adb logcat -d -t 1500 > artifacts/e2e/emulator-logcat-tail.txt 2>/dev/null || true
    adb shell dumpsys activity activities 2>/dev/null | grep -E "mResumedActivity|mFocusedApp|ANR" > artifacts/e2e/emulator-activities.txt || true
    adb shell dumpsys meminfo 2>/dev/null | tail -25 > artifacts/e2e/emulator-meminfo.txt || true
  fi
  kill $APPIUM_PID 2>/dev/null || true
  exit $status
}
trap collect_emulator_state EXIT

for _ in $(seq 1 30); do
  if curl -fs http://127.0.0.1:4723/status > /dev/null; then break; fi
  sleep 1
done
curl -fs http://127.0.0.1:4723/status > /dev/null || { echo "Appium did not start"; cat artifacts/e2e/appium.log; exit 1; }

E2E_REQUIRED=1 python -m pytest -m e2e -v --reruns 1 --reruns-delay 2 \
  --junitxml=artifacts/e2e/junit.xml --results-json=artifacts/e2e/results-e2e.json
