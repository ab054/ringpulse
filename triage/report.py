"""Step 5: one pull request comment: a summary table, then root cause, evidence and patch per failure."""
from __future__ import annotations

MARKER = "<!-- ringpulse-triage -->"
SOURCE_NOTE = {"prefilter": "known pattern, no model call", "model": "model diagnosis", "error": "no usable model answer",
               "limit": "over the per-run limit", "no_key": "no API key configured"}


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render(results: list[dict]) -> str:
    if not results:
        return ""
    lines = [MARKER, "## Test failure triage", "",
             f"{len(results)} failed test(s). The bot only suggests: nothing is pushed or merged, a person decides.", "",
             "| Test | Category | Fix in | Confidence | Fix check |", "|---|---|---|---|---|"]
    for r in results:
        d = r["diagnosis"]
        lines.append(f"| `{_cell(r['id'])}` | {d['category'] or 'unknown'} | {d['fix_target']} | {d['confidence']} | {r['verification']['status']} |")
    for r in results:
        d = r["diagnosis"]
        lines += ["", "---", f"### `{r['id']}`", "",
                  f"**{d['category'] or 'no diagnosis'}** ({SOURCE_NOTE.get(d['source'], d['source'])}). {d['root_cause']}", ""]
        if d["evidence"]:
            # a code block, not a quote: quoted source lines such as "# comment" would render as headings
            quoted = [e.replace("```", "'''").replace("\n", " ") for e in d["evidence"]]
            lines += ["Evidence:", "", "```text", *quoted, "```", ""]
        if d["category"] == "intended_change":
            lines += ["The pull request changed this behaviour on purpose. Update the expected value in the test, "
                      "and confirm the new behaviour with whoever owns it.", ""]
        status = r["verification"]
        lines.append(f"Fix check: **{status['status']}**" + (f" ({_cell(status['detail'])})" if status["detail"] else ""))
        if d["patch"]:
            lines += ["", "<details><summary>Suggested patch</summary>", "", "```diff", d["patch"].rstrip(), "```", "", "</details>"]
    return "\n".join(lines) + "\n"


def accuracy_line(results: list[dict]) -> str:
    verified = sum(1 for r in results if r["verification"]["status"] == "fix verified")
    return f"{len(results)} failures, {verified} fixes verified"
