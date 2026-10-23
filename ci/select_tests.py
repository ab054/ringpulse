"""Decide which test layers a change needs, and say why.

    python -m ci.select_tests --base <sha> --head <sha>      # what CI does for a pull request
    python -m ci.select_tests --files api/scoring.py README.md

Deterministic on purpose: the same diff always gives the same answer, from a map a human can read
(ci/test_map.yaml). Safety rules beat the map: anything uncertain runs everything.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ALL_LAYERS = ("unit", "data", "api", "sync", "e2e")
BACKEND_LAYERS = ("unit", "data", "api", "sync")
MAP_PATH = Path(__file__).with_name("test_map.yaml")
RUN_ALL_LABEL = "run-all-tests"
ALWAYS_ALL_EVENTS = ("push", "schedule", "workflow_dispatch")  # pull_request is the only one that may select


@dataclass
class Selection:
    layers: tuple[str, ...]
    run_all_reason: str | None = None
    # file -> (layers, why); layers None = the map does not know this file
    files: dict[str, tuple[tuple[str, ...] | None, str]] = field(default_factory=dict)

    @property
    def backend_layers(self):
        return tuple(l for l in self.layers if l in BACKEND_LAYERS)

    @property
    def run_mobile(self):
        return "e2e" in self.layers


def load_map(path: Path = MAP_PATH) -> list[dict]:
    rules = yaml.safe_load(path.read_text())["rules"]
    for rule in rules:
        unknown = set(rule["layers"]) - set(ALL_LAYERS)
        if unknown:
            raise ValueError(f"{path.name}: unknown layer {sorted(unknown)} in rule {rule['paths']}")
    return rules


def matching_rule(path: str, rules: list[dict]) -> dict | None:
    """The first rule whose glob matches: specific rules sit above general ones in the map."""
    return next((r for r in rules if any(fnmatch.fnmatchcase(path, pattern) for pattern in r["paths"])), None)


def select(changed: list[str], rules: list[dict], *, event: str = "pull_request",
           labels: tuple[str, ...] = (), diff_failed: bool = False) -> Selection:
    everything = tuple(ALL_LAYERS)
    if event in ALWAYS_ALL_EVENTS:
        return Selection(everything, f"event is {event}: full run")
    if RUN_ALL_LABEL in labels:
        return Selection(everything, f"label '{RUN_ALL_LABEL}' is set")
    if diff_failed:
        return Selection(everything, "could not compute the diff")
    if not changed:
        return Selection(everything, "diff is empty, so nothing proves a smaller run is safe")

    layers: set[str] = set()
    files: dict[str, tuple[tuple[str, ...] | None, str]] = {}
    unknown = []
    for path in changed:
        rule = matching_rule(path, rules)
        if rule is None:
            unknown.append(path)
            files[path] = (None, "not in ci/test_map.yaml")
            continue
        layers |= set(rule["layers"])
        files[path] = (tuple(l for l in ALL_LAYERS if l in rule["layers"]), rule["why"])
    if unknown:
        return Selection(everything, f"{unknown[0]} is not in the test map" + (f" (+{len(unknown) - 1} more)" if len(unknown) > 1 else ""), files)
    return Selection(tuple(l for l in ALL_LAYERS if l in layers), None, files)


def summary_markdown(sel: Selection) -> str:
    lines = ["## Test selection", ""]
    if sel.run_all_reason:
        lines += [f"**Running everything**: {sel.run_all_reason}.", ""]
    else:
        lines += [f"**Layers: {', '.join(sel.layers) or 'none (nothing testable changed)'}**", ""]
    lines += [f"Backend job: {'yes (' + ' or '.join(sel.backend_layers) + ')' if sel.backend_layers else 'skipped'}  ",
              f"Emulator job: {'yes' if sel.run_mobile else 'skipped'}", ""]
    if sel.files:
        lines += ["| Changed file | Layers | Why |", "|---|---|---|"]
        for path, (layers, why) in sel.files.items():
            lines.append(f"| `{path}` | {', '.join(layers) if layers else ('none' if layers == () else 'ALL (unknown file)')} | {why} |")
    return "\n".join(lines) + "\n"


def changed_files(base: str, head: str) -> list[str]:
    out = subprocess.run(["git", "diff", "--name-only", f"{base}...{head}"], capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if line]


def write_outputs(sel: Selection, path: str | None) -> None:
    values = {
        "layers": " ".join(sel.layers),
        "backend": "true" if sel.backend_layers else "false",
        "backend_markers": " or ".join(sel.backend_layers),
        "mobile": "true" if sel.run_mobile else "false",
    }
    text = "".join(f"{k}={v}\n" for k, v in values.items())
    if path:
        with open(path, "a") as f:
            f.write(text)
    else:
        print(text, end="")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--files", nargs="*", help="use this file list instead of git diff")
    parser.add_argument("--event", default=os.environ.get("GITHUB_EVENT_NAME", "pull_request"))
    parser.add_argument("--labels", default=os.environ.get("PR_LABELS", ""), help="comma-separated PR labels")
    args = parser.parse_args(argv)

    diff_failed = False
    if args.files is not None:
        changed = args.files
    elif args.base:
        try:
            changed = changed_files(args.base, args.head)
        except (subprocess.CalledProcessError, FileNotFoundError):
            changed, diff_failed = [], True
    else:
        changed, diff_failed = [], True

    labels = tuple(l.strip() for l in args.labels.split(",") if l.strip())
    sel = select(changed, load_map(), event=args.event, labels=labels, diff_failed=diff_failed)

    summary = summary_markdown(sel)
    print(summary, file=sys.stderr)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(summary)
    write_outputs(sel, os.environ.get("GITHUB_OUTPUT"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
