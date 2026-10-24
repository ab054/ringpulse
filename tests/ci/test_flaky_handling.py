"""Reruns, quarantine and test health: the plugin runs for real in a throw-away project, the rest is plain data."""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from ci import health as hl
from ci import test_results_plugin as plugin
from triage import prefilter

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]

PROJECT_TESTS = '''
import itertools
import pytest

calls = itertools.count()

def test_flaky():
    assert next(calls) > 0          # fails the first attempt only

def test_broken():
    assert False

def test_fine():
    pass

@pytest.mark.parametrize("n", [1, 2])
def test_param_broken(n):
    assert False

def test_skipped():
    pytest.skip("not today")
'''


def run_project(tmp_path, *, quarantine=None, extra=(), tests=PROJECT_TESTS):
    pytest.importorskip("pytest_rerunfailures")
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "test_sample.py").write_text(tests)
    if quarantine is not None:
        (tmp_path / "quarantine.yaml").write_text(yaml.safe_dump({"quarantined": quarantine}))
    out = tmp_path / "results.json"
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    env.pop("GITHUB_STEP_SUMMARY", None)
    run = subprocess.run([sys.executable, "-m", "pytest", "-p", "ci.test_results_plugin", "--reruns", "1", "-p", "no:cacheprovider",
                          "--results-json", str(out), "-q", *extra], cwd=tmp_path, env=env, capture_output=True, text=True)
    return run, json.loads(out.read_text())["tests"]


def test_rerun_separates_flaky_from_broken_from_fine(tmp_path):
    run, tests = run_project(tmp_path)

    assert tests["test_sample.py::test_flaky"] == {"status": "flaky", "attempts": 2}
    assert tests["test_sample.py::test_broken"] == {"status": "failed", "attempts": 2}
    assert tests["test_sample.py::test_fine"] == {"status": "passed", "attempts": 1}
    assert tests["test_sample.py::test_skipped"]["status"] == "skipped"
    assert run.returncode == 1                          # the broken tests still fail the run
    assert "FLAKY (failed, then passed on rerun): test_sample.py::test_flaky" in run.stdout


def test_a_run_with_only_a_flaky_test_passes_but_says_so(tmp_path):
    run, tests = run_project(tmp_path, tests=PROJECT_TESTS.split("def test_broken")[0] + "def test_fine():\n    pass\n")

    assert run.returncode == 0 and tests["test_sample.py::test_flaky"]["status"] == "flaky"
    assert "flaky" in run.stdout


def test_quarantined_tests_still_run_but_do_not_fail_the_build(tmp_path):
    run, tests = run_project(tmp_path, quarantine=["test_sample.py::test_broken", "test_sample.py::test_param_broken"])

    assert tests["test_sample.py::test_broken"]["status"] == "quarantined_failed"
    assert tests["test_sample.py::test_param_broken[1]"]["status"] == "quarantined_failed"   # base name covers the parameters
    assert tests["test_sample.py::test_param_broken[2]"]["status"] == "quarantined_failed"
    assert run.returncode == 0
    assert "QUARANTINED, still failing" in run.stdout


def test_a_quarantined_test_that_passes_is_recorded_as_such(tmp_path):
    _, tests = run_project(tmp_path, quarantine=["test_sample.py::test_fine"])
    assert tests["test_sample.py::test_fine"]["status"] == "quarantined_passed"


def test_quarantine_matching_rules():
    assert plugin.is_quarantined("a.py::t[1]", {"a.py::t[1]"})
    assert plugin.is_quarantined("a.py::t[1]", {"a.py::t"})
    assert not plugin.is_quarantined("a.py::t2", {"a.py::t"})
    assert not plugin.is_quarantined("a.py::t", set())


def test_the_triage_bot_reads_the_same_quarantine_file(tmp_path):
    hl.apply_quarantine(tmp_path / "quarantine.yaml", ["a.py::t"], [])
    assert prefilter.load_quarantine(tmp_path / "quarantine.yaml") == {"a.py::t"}


# ---- health ------------------------------------------------------------------------------------

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


def run_of(**statuses):
    return {name: {"status": status, "attempts": 1} for name, status in statuses.items()}


def record(health, results, day=0):
    return hl.update(health, results, run_id=str(day), now=NOW + timedelta(days=day))


def test_history_counts_pass_flaky_and_fail_and_ignores_skips():
    health = {}
    for status in ("passed", "flaky", "failed", "skipped"):
        record(health, run_of(t=status))

    entry = health["tests"]["t"]
    assert entry["history"] == ["pass", "flaky", "fail"]
    s = hl.stats(entry)
    assert (s["runs"], s["flakes"], s["failures"]) == (3, 1, 1)
    assert s["first_try_pass_rate"] == pytest.approx(1 / 3) and s["pass_rate"] == pytest.approx(2 / 3)


def test_history_is_a_rolling_window():
    health = {}
    for i in range(hl.WINDOW + 10):
        record(health, run_of(t="flaky" if i < 10 else "passed"))
    assert len(health["tests"]["t"]["history"]) == hl.WINDOW
    assert "flaky" not in health["tests"]["t"]["history"]       # old flakes fell out of the window


def test_run_summaries_and_stale_tests():
    health = {}
    record(health, run_of(old="passed", kept="passed"), day=0)
    record(health, run_of(kept="passed"), day=hl.STALE_DAYS + 1)
    assert set(health["tests"]) == {"kept"}                      # a deleted or renamed test disappears
    assert health["runs"][-1] == {"id": str(hl.STALE_DAYS + 1), "at": health["runs"][-1]["at"], "total": 1, "passed": 1, "flaky": 0, "failed": 0}


def test_a_test_is_quarantined_after_enough_flakes_but_a_broken_test_never_is():
    health = {}
    for i in range(hl.FLAKES_TO_QUARANTINE):
        record(health, run_of(shaky="flaky", broken="failed", steady="passed"), day=i)
    record(health, run_of(shaky="passed", broken="failed", steady="passed"), day=9)

    add, release = hl.suggest_quarantine(health, set())

    assert add == ["shaky"] and release == []


def test_two_flakes_are_not_enough_and_already_quarantined_tests_are_not_added_again():
    health = {}
    for i in range(hl.FLAKES_TO_QUARANTINE - 1):
        record(health, run_of(few="flaky"), day=i)
    for i in range(hl.FLAKES_TO_QUARANTINE):
        record(health, run_of(listed="flaky"), day=i)
    assert hl.suggest_quarantine(health, {"listed"})[0] == []
    assert "few" not in hl.suggest_quarantine(health, set())[0]


def test_a_quarantined_test_is_released_after_a_long_clean_streak():
    health = {}
    for i in range(hl.CLEAN_RUNS_TO_RELEASE - 1):
        record(health, run_of(t="quarantined_passed"), day=i)
    assert hl.suggest_quarantine(health, {"t"})[1] == []
    record(health, run_of(t="passed"), day=99)
    assert hl.suggest_quarantine(health, {"t"})[1] == ["t"]
    record(health, run_of(t="quarantined_failed"), day=100)
    assert hl.suggest_quarantine(health, {"t"})[1] == []


def test_apply_quarantine_edits_the_file_and_reports_whether_it_changed(tmp_path):
    path = tmp_path / "quarantine.yaml"
    assert hl.apply_quarantine(path, ["b::t", "a::t"], []) is True
    assert yaml.safe_load(path.read_text()) == {"quarantined": ["a::t", "b::t"]}
    assert path.read_text().startswith("# Tests that still run")
    assert hl.apply_quarantine(path, ["a::t"], []) is False       # nothing new: no diff, no pull request
    assert hl.apply_quarantine(path, [], ["a::t"]) is True
    assert yaml.safe_load(path.read_text()) == {"quarantined": ["b::t"]}


def test_report_lists_the_flakiest_tests_first():
    health = {}
    for i in range(4):
        record(health, run_of(shaky="flaky" if i % 2 else "passed", steady="passed"), day=i)
    text = hl.report(health)
    assert "`shaky`" in text and "`steady`" not in text and "Test health" in text
    assert "No runs recorded yet" in hl.report({})


def test_cli_update_then_quarantine(tmp_path):
    results = tmp_path / "r.json"
    results.write_text(json.dumps({"tests": run_of(shaky="flaky")}))
    health = tmp_path / "health.json"
    for i in range(hl.FLAKES_TO_QUARANTINE):
        hl.main(["update", "--results", str(results), str(tmp_path / "missing.json"), "--health", str(health), "--run-id", str(i)])

    hl.main(["quarantine", "--health", str(health), "--file", str(tmp_path / "quarantine.yaml")])

    assert yaml.safe_load((tmp_path / "quarantine.yaml").read_text()) == {"quarantined": ["shaky"]}


def test_a_test_that_was_flaky_but_now_fails_every_time_is_broken_not_quarantined():
    health = {}
    for i, status in enumerate(["flaky"] * hl.FLAKES_TO_QUARANTINE + ["failed"] * 3):
        record(health, run_of(t=status), day=i)
    assert hl.suggest_quarantine(health, set())[0] == []


# ---- the pipeline is wired to it ----------------------------------------------------------------

def test_ci_retries_failures_and_records_results_in_both_test_jobs():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    backend = next(s for s in workflow["jobs"]["backend"]["steps"] if "pytest" in s.get("run", ""))["run"]
    e2e = (ROOT / "ci/run_e2e.sh").read_text()
    for command in (backend, e2e):
        assert "--reruns 1" in command and "--results-json" in command


def test_the_health_job_never_runs_on_pull_requests_and_only_it_can_write():
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    assert "pull_request" in jobs["health"]["if"]
    assert jobs["health"]["permissions"]["contents"] == "write"
    assert all("contents" in j.get("permissions", {"contents": "read"}) and j.get("permissions", {}).get("contents", "read") == "read"
               for name, j in jobs.items() if name != "health")
    assert "health" not in jobs["result"]["needs"]      # recording history must never decide whether a PR is green


def test_nothing_to_change_does_not_create_an_empty_quarantine_file(tmp_path):
    """The nightly job used to open a pull request adding an empty file, every run."""
    path = tmp_path / "quarantine.yaml"
    assert hl.apply_quarantine(path, [], []) is False
    assert not path.exists()


def test_main_runs_are_never_cancelled_and_a_cancelled_run_is_not_recorded_as_health():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    assert "run_id" in workflow["concurrency"]["group"]                      # every non-PR run has its own group
    assert "pull_request" in workflow["concurrency"]["cancel-in-progress"]   # only PR runs are cancelled by newer pushes
    assert "'cancelled'" in workflow["jobs"]["health"]["if"]


def test_the_nightly_job_does_not_open_a_second_quarantine_pull_request():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert 'startswith("bot/quarantine-")' in workflow
