"""Measure a model version on the eval set and gate it against the current one.

    python -m ai.evaluate                        # metrics for the active model
    python -m ai.evaluate --candidate v2 --baseline v1
                                                 # gate: exit 1 if v2 must not ship

Gate rules (the same idea as "the new readiness formula stays within 5 points of the old one"):
  * recall on positives: no slice may drop more than RECALL_SLICE_TOLERANCE below the baseline,
    and the overall recall must stay above RECALL_FLOOR (a missed alert is the expensive mistake);
  * false-alarm rate on negatives: no slice may rise more than FALSE_ALARM_TOLERANCE.
An overall average is never enough on its own: it can improve while one condition gets much worse.
"""
import argparse
import sys
from dataclasses import dataclass

from ai.detector import active_version, detect
from ai.evalset import SLICES, build

RECALL_FLOOR = 0.85
RECALL_SLICE_TOLERANCE = 0.05
FALSE_ALARM_TOLERANCE = 0.05


@dataclass(frozen=True)
class SliceResult:
    slice: str
    positive: bool  # True: the slice holds ill nights, the rate is recall; else false-alarm rate
    cases: int
    rate: float


def evaluate(version: str, cases=None) -> dict[str, SliceResult]:
    cases = cases if cases is not None else build()
    hits: dict[str, list[bool]] = {}
    for case in cases:
        detection = detect(case.samples, version)
        flagged = detection is not None and detection.label is not None
        hits.setdefault(case.slice, []).append(flagged)
    return {
        name: SliceResult(name, SLICES[name], len(flags), sum(flags) / len(flags))
        for name, flags in hits.items()
    }


def overall_recall(results: dict[str, SliceResult]) -> float:
    positives = [r for r in results.values() if r.positive]
    return sum(r.rate * r.cases for r in positives) / sum(r.cases for r in positives)


def gate(candidate: dict[str, SliceResult], baseline: dict[str, SliceResult]) -> list[str]:
    """Reasons the candidate must not ship. Empty list = it may ship."""
    problems = []
    if overall_recall(candidate) < RECALL_FLOOR:
        problems.append(f"overall recall {overall_recall(candidate):.2f} is below the floor {RECALL_FLOOR}")
    for name, c in candidate.items():
        b = baseline[name]
        if c.positive and c.rate < b.rate - RECALL_SLICE_TOLERANCE:
            problems.append(f"{name}: recall fell from {b.rate:.2f} to {c.rate:.2f}")
        if not c.positive and c.rate > b.rate + FALSE_ALARM_TOLERANCE:
            problems.append(f"{name}: false alarms rose from {b.rate:.2f} to {c.rate:.2f}")
    return problems


def table(results: dict[str, dict[str, SliceResult]]) -> str:
    versions = list(results)
    lines = ["| Slice | Measures | Cases | " + " | ".join(versions) + " |",
             "|---|---|---|" + "---|" * len(versions)]
    for name in SLICES:
        first = results[versions[0]][name]
        measure = "recall" if first.positive else "false alarms"
        cells = " | ".join(f"{results[v][name].rate:.2f}" for v in versions)
        lines.append(f"| {name} | {measure} | {first.cases} | {cells} |")
    lines.append("| **all ill nights** | recall | | " + " | ".join(f"{overall_recall(results[v]):.2f}" for v in versions) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--candidate", help="model version to gate")
    parser.add_argument("--baseline", default=None, help="model version it must not be worse than (default: active)")
    args = parser.parse_args(argv)

    cases = build()
    baseline_version = args.baseline or active_version()
    if not args.candidate:
        print(table({baseline_version: evaluate(baseline_version, cases)}))
        return 0
    baseline = evaluate(baseline_version, cases)
    candidate = evaluate(args.candidate, cases)
    print(table({baseline_version: baseline, args.candidate: candidate}))
    problems = gate(candidate, baseline)
    print()
    if problems:
        print(f"GATE FAILED: {args.candidate} must not replace {baseline_version}")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"GATE PASSED: {args.candidate} may replace {baseline_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
