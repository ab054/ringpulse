"""Test health over time: pass rate and flake count per test, a rolling window, and quarantine suggestions.

    python -m ci.health update --results a.json b.json --health health.json --run-id 123
    python -m ci.health report --health health.json
    python -m ci.health quarantine --health health.json --file quarantine.yaml

Input is the --results-json file written by ci/test_results_plugin.py. health.json lives on the `ci-health`
branch (not main), so recording a run never needs a pull request.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

WINDOW = 30            # results kept per test
MAX_RUNS = 100         # run summaries kept
FLAKES_TO_QUARANTINE = 3
CLEAN_RUNS_TO_RELEASE = 20
STALE_DAYS = 30
CODE = {"passed": "pass", "flaky": "flaky", "failed": "fail", "quarantined_failed": "qfail", "quarantined_passed": "qpass"}
GOOD = ("pass", "qpass")
QUARANTINE_HEADER = """# Tests that still run but no longer block merges (xfail, non-strict).
# Managed by the nightly health job, which proposes changes in a pull request. Edit by hand if you need to.
"""


def load_results(paths) -> dict[str, dict]:
    tests: dict[str, dict] = {}
    for path in paths:
        if Path(path).is_file():
            tests.update(json.loads(Path(path).read_text())["tests"])
    return tests


def update(health: dict, results: dict[str, dict], *, run_id: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    health.setdefault("tests", {})
    health.setdefault("runs", [])
    counts = {"total": 0, "passed": 0, "flaky": 0, "failed": 0}
    for nodeid, result in results.items():
        code = CODE.get(result["status"])
        if code is None:      # skipped: says nothing about health
            continue
        entry = health["tests"].setdefault(nodeid, {"history": []})
        entry["history"] = (entry["history"] + [code])[-WINDOW:]
        entry["last_seen"] = now.isoformat(timespec="seconds")
        counts["total"] += 1
        counts[{"pass": "passed", "qpass": "passed", "flaky": "flaky"}.get(code, "failed")] += 1
    health["runs"] = (health["runs"] + [{"id": str(run_id), "at": now.isoformat(timespec="seconds"), **counts}])[-MAX_RUNS:]
    cutoff = (now - timedelta(days=STALE_DAYS)).isoformat(timespec="seconds")
    health["tests"] = {k: v for k, v in health["tests"].items() if v["last_seen"] >= cutoff}   # renamed or deleted tests
    return health


def stats(entry: dict) -> dict:
    history = entry["history"]
    runs = len(history)
    return {"runs": runs,
            "flakes": history.count("flaky"),
            "failures": history.count("fail") + history.count("qfail"),
            "first_try_pass_rate": sum(c in GOOD for c in history) / runs if runs else 1.0,
            "pass_rate": sum(c in GOOD + ("flaky",) for c in history) / runs if runs else 1.0}


def suggest_quarantine(health: dict, quarantined: set[str]) -> tuple[list[str], list[str]]:
    """(tests to add, tests that earned release). A test that fails every time is broken, not flaky: never added."""
    add, release = [], []
    for nodeid, entry in sorted(health["tests"].items()):
        history = entry["history"]
        if nodeid in quarantined:
            if len(history) >= CLEAN_RUNS_TO_RELEASE and all(c in GOOD for c in history[-CLEAN_RUNS_TO_RELEASE:]):
                release.append(nodeid)
        elif history.count("flaky") >= FLAKES_TO_QUARANTINE and history[-3:] != ["fail"] * 3:
            add.append(nodeid)
    return add, release


def apply_quarantine(path: Path, add: list[str], release: list[str]) -> bool:
    current = []
    if path.is_file():
        current = (yaml.safe_load(path.read_text()) or {}).get("quarantined", [])
    updated = sorted((set(current) | set(add)) - set(release))
    if updated == sorted(current) and path.is_file():
        return False
    path.write_text(QUARANTINE_HEADER + yaml.safe_dump({"quarantined": updated}, sort_keys=True))
    return True


def report(health: dict) -> str:
    runs = health.get("runs", [])
    if not runs:
        return "## Test health\n\nNo runs recorded yet.\n"
    recent = runs[-10:]
    total = sum(r["total"] for r in recent) or 1
    lines = ["## Test health", "",
             f"Last {len(recent)} recorded runs: **{100 * sum(r['passed'] for r in recent) / total:.1f}%** of test results passed first time, "
             f"**{sum(r['flaky'] for r in recent)}** flaky, **{sum(r['failed'] for r in recent)}** failed.", ""]
    rows = sorted(((n, stats(e)) for n, e in health["tests"].items()), key=lambda r: (-r[1]["flakes"], r[1]["first_try_pass_rate"]))
    rows = [r for r in rows if r[1]["flakes"] or r[1]["failures"]][:10]
    if rows:
        lines += ["| Test | Runs | First-try pass | Flaky | Failed |", "|---|---|---|---|---|"]
        lines += [f"| `{n}` | {s['runs']} | {100 * s['first_try_pass_rate']:.0f}% | {s['flakes']} | {s['failures']} |" for n, s in rows]
    else:
        lines.append("No flaky or failing tests in the window.")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    up = sub.add_parser("update")
    up.add_argument("--results", nargs="+", required=True)
    up.add_argument("--health", required=True)
    up.add_argument("--run-id", required=True)
    rep = sub.add_parser("report")
    rep.add_argument("--health", required=True)
    quar = sub.add_parser("quarantine")
    quar.add_argument("--health", required=True)
    quar.add_argument("--file", default="quarantine.yaml")
    args = parser.parse_args(argv)

    path = Path(args.health)
    health = json.loads(path.read_text()) if path.is_file() and path.read_text().strip() else {}
    if args.command == "update":
        results = load_results(args.results)
        if not results:                      # every test job was skipped or died before writing results
            print("no results to record")
            return 0
        path.write_text(json.dumps(update(health, results, run_id=args.run_id), indent=1, sort_keys=True))
    elif args.command == "report":
        print(report(health))
    else:
        file = Path(args.file)
        current = set(yaml.safe_load(file.read_text()).get("quarantined", [])) if file.is_file() else set()
        add, release = suggest_quarantine(health, current)
        changed = apply_quarantine(file, add, release)
        print(json.dumps({"changed": changed, "add": add, "release": release}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
