"""pytest plugin: records what really happened to every test, and applies the quarantine list.

JUnit cannot tell a test that failed and then passed on a rerun from one that passed first time
(pytest-rerunfailures writes each attempt as its own passing-looking entry), so this plugin keeps its own record:

    pytest --reruns 1 --results-json results.json

Statuses: passed, flaky (failed, then passed on a rerun), failed (failed every attempt), skipped,
quarantined_failed, quarantined_passed.

Quarantine: tests listed in quarantine.yaml still run, but a failure no longer fails the build (xfail, non-strict).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

QUARANTINE_FILE = "quarantine.yaml"


def pytest_addoption(parser):
    parser.addoption("--results-json", default=None, help="write per-test outcomes (with rerun info) to this file")


def load_quarantine(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return list((yaml.safe_load(path.read_text()) or {}).get("quarantined", []))


def is_quarantined(nodeid: str, quarantined) -> bool:
    """An entry matches a test exactly, or all parameter variants of it (the id without [..])."""
    return nodeid in quarantined or nodeid.split("[")[0] in quarantined


def pytest_configure(config):
    config._ringpulse = {"attempts": {}, "final": {}, "reran": {}, "quarantined": set()}
    _current["state"] = config._ringpulse  # logreport hooks get no config, so they reach the state through here


def pytest_collection_modifyitems(config, items):
    quarantined = set(load_quarantine(Path(config.rootpath) / QUARANTINE_FILE))
    for item in items:
        if is_quarantined(item.nodeid, quarantined):
            config._ringpulse["quarantined"].add(item.nodeid)
            item.add_marker(pytest.mark.xfail(reason="quarantined (see quarantine.yaml)", strict=False))


def pytest_runtest_logreport(report):
    state = _state()
    if state is None:
        return
    nodeid = report.nodeid
    if report.outcome == "rerun":
        state["reran"][nodeid] = state["reran"].get(nodeid, 0) + 1
        return
    if report.when == "call":
        state["attempts"][nodeid] = state["attempts"].get(nodeid, 0) + 1
        if hasattr(report, "wasxfail"):
            state["final"][nodeid] = "quarantined_failed" if report.outcome == "skipped" else "quarantined_passed"
        else:
            state["final"][nodeid] = report.outcome
    elif report.when == "setup" and report.outcome in ("failed", "skipped"):
        state["final"][nodeid] = report.outcome
    elif report.when == "teardown" and report.outcome == "failed":
        state["final"][nodeid] = "failed"


_current = {}


def _state():
    return _current.get("state")


def statuses(state: dict) -> dict[str, dict]:
    result = {}
    for nodeid, final in state["final"].items():
        reruns = state["reran"].get(nodeid, 0)
        status = {"passed": "flaky" if reruns else "passed"}.get(final, final)
        # rerun attempts report as "rerun" and are not in `attempts`, so add them back
        result[nodeid] = {"status": status, "attempts": state["attempts"].get(nodeid, 1) + reruns}
    return result


def pytest_sessionfinish(session):
    state = session.config._ringpulse
    path = session.config.getoption("--results-json")
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({"tests": statuses(state)}, indent=1, sort_keys=True))


def pytest_terminal_summary(terminalreporter, config):
    found = statuses(config._ringpulse)
    flaky = sorted(n for n, r in found.items() if r["status"] == "flaky")
    quarantined_failed = sorted(n for n, r in found.items() if r["status"] == "quarantined_failed")
    if not (flaky or quarantined_failed):
        return
    terminalreporter.section("flaky and quarantined tests")
    for nodeid in flaky:
        terminalreporter.write_line(f"FLAKY (failed, then passed on rerun): {nodeid}")
    for nodeid in quarantined_failed:
        terminalreporter.write_line(f"QUARANTINED, still failing (does not block): {nodeid}")
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        lines = ["## Flaky and quarantined tests", ""]
        lines += [f"- flaky: `{n}`" for n in flaky] + [f"- quarantined and failing: `{n}`" for n in quarantined_failed]
        with open(summary_file, "a") as f:
            f.write("\n".join(lines) + "\n")
