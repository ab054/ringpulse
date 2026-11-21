"""Ingest -> AI layer -> alerts, through the API.

Most tests run the worker's step directly (deterministic, no threads). One test runs the real
background worker and waits for the result by condition, the way an async pipeline must be tested.
"""
import random
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api.alerts import RecordingNotifier
from api.main import create_app
from ring_sim import RingSimulator, faults
from ring_sim.generate import synth_samples

pytestmark = pytest.mark.api

T0 = datetime(2026, 11, 20, 7, 0, tzinfo=timezone.utc)


class Clock:
    """A clock the test moves by hand."""

    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


def sick_night(device_id="ring-a", night_id="night-sick"):
    profile = dict(hours=8, hr=63, hrv=36, temp=37.1, restless=0.04)
    return {"night_id": night_id, "device_id": device_id,
            "samples": synth_samples(profile, random.Random(night_id))}


@pytest.fixture
def pipeline(tmp_path):
    """An API with a hand-moved clock and a recording notifier, worker off; step() runs it once."""
    clock, notifier = Clock(), RecordingNotifier()
    app = create_app(str(tmp_path / "p.db"), clock=clock, notifier=notifier, start_worker=False)
    client = TestClient(app)
    client.clock, client.notifier, client.step = clock, notifier, app.state.worker_step
    return client


def test_a_complete_night_is_queued_then_analysed(pipeline, ring):
    sim = ring("good_night")
    sim.sync(pipeline)

    queued = pipeline.get(f"/nights/{sim.night_id}/analysis")
    assert (queued.status_code, queued.json()["status"]) == (202, "queued")

    pipeline.step()

    done = pipeline.get(f"/nights/{sim.night_id}/analysis").json()
    assert done["status"] == "done"
    assert (done["label"], done["model_version"], done["readiness"]) == (None, "v1", 93)


def test_a_partial_night_is_not_analysed_until_it_is_complete(pipeline, ring):
    sim = ring("good_night")
    sim.sync(pipeline, faults.drop_seqs(sim.packets(), [3]))
    pipeline.step()
    assert pipeline.get(f"/nights/{sim.night_id}/analysis").json()["status"] == "waiting_for_data"

    sim.sync(pipeline, [p for p in sim.packets() if p["seq"] == 3])
    pipeline.step()
    assert pipeline.get(f"/nights/{sim.night_id}/analysis").json()["status"] == "done"


def test_a_sick_night_raises_one_alert_and_delivers_it(pipeline):
    sim = RingSimulator(sick_night())
    sim.sync(pipeline)
    pipeline.step()

    alerts = pipeline.get("/alerts", params={"device_id": "ring-a"}).json()
    assert [a["rule_id"] for a in alerts] == ["illness_signs"]
    assert [a["rule_id"] for a in pipeline.notifier.sent] == ["illness_signs"]


def test_syncing_the_same_night_again_does_not_alert_twice(pipeline):
    sim = RingSimulator(sick_night())
    sim.sync(pipeline)
    pipeline.step()
    sim.sync(pipeline)  # the phone retries: every packet is a duplicate
    pipeline.step()

    assert len(pipeline.get("/alerts", params={"device_id": "ring-a"}).json()) == 1
    assert len(pipeline.notifier.sent) == 1


def test_two_sick_nights_in_a_day_are_one_alert_with_a_count(pipeline):
    RingSimulator(sick_night(night_id="n1")).sync(pipeline)
    pipeline.step()
    pipeline.clock.now += timedelta(hours=20)
    RingSimulator(sick_night(night_id="n2")).sync(pipeline)
    pipeline.step()

    alerts = pipeline.get("/alerts", params={"device_id": "ring-a"}).json()
    assert [(a["rule_id"], a["occurrences"]) for a in alerts] == [("illness_signs", 2)]


def test_alerts_never_leak_to_another_device(pipeline):
    RingSimulator(sick_night(device_id="ring-a")).sync(pipeline)
    pipeline.step()

    assert pipeline.get("/alerts", params={"device_id": "ring-b"}).json() == []


def test_a_silent_device_raises_an_alert_after_the_limit(pipeline, ring):
    ring("good_night").sync(pipeline)
    pipeline.clock.now += timedelta(hours=35)
    pipeline.step()
    assert pipeline.get("/alerts", params={"device_id": "ring-sim-01"}).json() == []

    pipeline.clock.now += timedelta(hours=2)
    pipeline.step()
    assert [a["rule_id"] for a in pipeline.get("/alerts", params={"device_id": "ring-sim-01"}).json()] == ["device_silent"]


def wait_until(check, timeout=10.0, interval=0.05):
    """Poll until check() returns something truthy; fail with the last value seen. Never a fixed sleep."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = check()
        if last:
            return last
        time.sleep(interval)
    pytest.fail(f"condition not met within {timeout}s; last value: {last!r}")


def test_the_background_worker_turns_a_sync_into_an_alert(tmp_path):
    app = create_app(str(tmp_path / "w.db"), start_worker=True, worker_interval=0.05)
    with TestClient(app) as client:  # `with` runs the app's lifespan, which starts the worker
        RingSimulator(sick_night()).sync(client)

        alerts = wait_until(lambda: client.get("/alerts", params={"device_id": "ring-a"}).json())

    assert [a["rule_id"] for a in alerts] == ["illness_signs"]
