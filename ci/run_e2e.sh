#!/usr/bin/env bash
# Runs inside the emulator (android-emulator-runner calls this once the emulator has booted).
# Starts the Appium server, waits until it answers, then runs the emulator tests.
set -euo pipefail

mkdir -p artifacts/e2e
appium --log-level warn > artifacts/e2e/appium.log 2>&1 &
APPIUM_PID=$!
trap 'kill $APPIUM_PID 2>/dev/null || true' EXIT

for _ in $(seq 1 30); do
  if curl -fs http://127.0.0.1:4723/status > /dev/null; then break; fi
  sleep 1
done
curl -fs http://127.0.0.1:4723/status > /dev/null || { echo "Appium did not start"; cat artifacts/e2e/appium.log; exit 1; }

E2E_REQUIRED=1 python -m pytest -m e2e -v --junitxml=artifacts/e2e/junit.xml
