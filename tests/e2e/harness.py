"""Shared plumbing for the emulator tests: where things are, the live API process, failure artifacts."""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
# The app is built to call the API at 10.0.2.2:8000 (the emulator's name for this computer).
API_PORT = 8000
API_URL = f"http://127.0.0.1:{API_PORT}"
APPIUM_URL = os.environ.get("APPIUM_URL", "http://127.0.0.1:4723")
APK_PATH = Path(os.environ.get("RINGPULSE_APK", REPO_ROOT / "app/build/outputs/apk/debug/app-debug.apk"))
ARTIFACTS_DIR = REPO_ROOT / "artifacts" / "e2e"


class ApiServer:
    """A real uvicorn process with its own empty database."""

    def __init__(self, db_path: Path, log_path: Path):
        self.db_path = db_path
        self.log_path = log_path
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        if self._port_in_use():
            pytest.fail(f"Port {API_PORT} is already in use. Stop any API you started by hand and run again.")
        log = open(self.log_path, "w")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api.main:create_app", "--factory", "--port", str(API_PORT)],
            cwd=REPO_ROOT,
            env={**os.environ, "RINGPULSE_DB": str(self.db_path)},
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                break
            try:
                if httpx.get(f"{API_URL}/health", timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.2)
        self.stop()
        pytest.fail(f"API did not start. Log:\n{self.log_path.read_text()[-2000:]}")

    def stop(self) -> None:
        """Safe to call twice. Tests call it to simulate the API going away."""
        if self.process is None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.process = None

    @staticmethod
    def _port_in_use() -> bool:
        try:
            httpx.get(f"{API_URL}/health", timeout=1)
            return True
        except httpx.HTTPError:
            return False


def failed_in_test(node) -> bool:
    """True if the test failed in setup (a fixture such as 'wait for the Today screen') or in its body.
    Checking only the body missed every setup failure, which is exactly when the emulator itself is the suspect."""
    return any(getattr(getattr(node, f"rep_{phase}", None), "failed", False) for phase in ("setup", "call"))


def save_failure_artifacts(session, test_name: str, root: Path = ARTIFACTS_DIR) -> Path:
    """Screenshot, page source and logcat for a failed test. Never raises: capturing must not hide the failure."""
    folder = root / re.sub(r"[^A-Za-z0-9_.-]+", "_", test_name)
    folder.mkdir(parents=True, exist_ok=True)

    def capture(filename, produce):
        try:
            produce(folder / filename)
        except Exception as error:  # noqa: BLE001 - best effort by design
            (folder / f"{filename}.error.txt").write_text(f"{type(error).__name__}: {error}\n")

    capture("screenshot.png", lambda path: session.save_screenshot(str(path)))
    capture("page_source.xml", lambda path: path.write_text(session.page_source))
    capture(
        "logcat.txt",
        lambda path: path.write_text(
            "\n".join(f"{e.get('timestamp')} {e.get('level')} {e.get('message')}" for e in session.get_log("logcat"))
        ),
    )
    return folder
