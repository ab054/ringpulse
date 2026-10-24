"""python -m triage --junit backend=junit-backend.xml e2e=artifacts/e2e/junit.xml --base <sha> --head <sha>

Writes triage-results.json and triage-report.md. Always exits 0: a broken triage step must not
turn a red build into a different red build."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from . import diagnose as dg
from . import prefilter, report, verify
from .bundle import build_bundle


def pr_context(base: str | None, head: str) -> dict:
    diff = ""
    if base:
        out = subprocess.run(["git", "diff", f"{base}...{head}"], capture_output=True, text=True)
        diff = out.stdout if out.returncode == 0 else ""
    return {"title": os.environ.get("PR_TITLE", ""), "body": os.environ.get("PR_BODY", ""), "diff": diff}


def triage(failures: list[dict], pr: dict, repo: Path, client_factory, quarantined: set[str]) -> list[dict]:
    results, sent, client = [], 0, None
    for failure in failures:
        diagnosis = prefilter.prefilter(failure, quarantined)
        if diagnosis is None:
            if sent >= dg.MAX_FAILURES:
                diagnosis = _non_answer("More failures than the per-run limit; this one was not sent to the model.", "limit")
            else:
                client = client or client_factory()
                if client is None:
                    diagnosis = _non_answer("No ANTHROPIC_API_KEY is configured for this run, so there is no diagnosis.", "no_key")
                else:
                    sent += 1
                    diagnosis = dg.diagnose(failure, pr, client)
        status, detail = verify.verify(diagnosis["patch"], diagnosis["fix_target"], [failure["id"]], repo, kind=failure["kind"])
        results.append({"id": failure["id"], "kind": failure["kind"], "diagnosis": diagnosis,
                        "verification": {"status": status, "detail": detail}})
    return results


def _non_answer(why: str, source: str) -> dict:
    return {"category": None, "fix_target": "none", "root_cause": why, "evidence": [], "patch": "", "confidence": "low", "source": source}


def make_client():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    import anthropic
    return anthropic.Anthropic()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--junit", nargs="+", required=True, help="kind=path pairs, e.g. backend=junit-backend.xml")
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--artifacts", default="artifacts/e2e")
    parser.add_argument("--out", default=".")
    args = parser.parse_args(argv)

    repo, out = Path(args.repo).resolve(), Path(args.out)
    try:
        junit = dict(pair.split("=", 1) for pair in args.junit)
        failures = build_bundle({k: Path(v) for k, v in junit.items()}, repo, artifacts_dir=Path(args.artifacts))
        results = triage(failures, pr_context(args.base, args.head), repo, make_client,
                         prefilter.load_quarantine(repo / "quarantine.yaml"))
    except Exception as error:  # noqa: BLE001
        print(f"triage failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 0
    (out / "triage-results.json").write_text(json.dumps(results, indent=2))
    (out / "triage-report.md").write_text(report.render(results))
    print(report.accuracy_line(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
