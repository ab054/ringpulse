"""Step 3: one model call per failed test, with a fixed prompt and a required JSON answer."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

HERE = Path(__file__).parent
DEFAULT_MODEL = "claude-sonnet-5-5"  # versioned here and in the repo, overridable with TRIAGE_MODEL
MAX_FAILURES = 5          # failures sent to the model per run
MAX_DIFF_CHARS = 12000    # PR diff budget per call
MAX_OUTPUT_TOKENS = 1500

SCHEMA = json.loads((HERE / "schema.json").read_text())
SECRET_PATTERNS = [
    r"sk-ant-[A-Za-z0-9_-]{10,}", r"gh[pousr]_[A-Za-z0-9]{20,}", r"github_pat_[A-Za-z0-9_]{20,}",
    r"AKIA[0-9A-Z]{16}", r"(?i)bearer\s+[A-Za-z0-9._-]{16,}", r"(?i)(api[_-]?key|token|secret|password)\s*[=:]\s*\S{6,}",
]


def scrub(text: str) -> str:
    """Remove anything that looks like a credential before text leaves the machine."""
    for secret in (os.environ.get("ANTHROPIC_API_KEY"), os.environ.get("GITHUB_TOKEN")):
        if secret and len(secret) > 8:
            text = text.replace(secret, "[REDACTED]")
    for pattern in SECRET_PATTERNS:
        text = re.sub(pattern, "[REDACTED]", text)
    return text


def build_message(failure: dict, pr: dict) -> str:
    evidence = "\n".join(f"--- {name} ---\n{content}" for name, content in failure["evidence_files"].items())
    body = (
        f"<pr_title>{pr.get('title', '')}</pr_title>\n"
        f"<pr_description>{pr.get('body', '')}</pr_description>\n"
        f"<pr_diff>\n{pr.get('diff', '')[:MAX_DIFF_CHARS]}\n</pr_diff>\n"
        f"<failure>\ntest: {failure['id']}\nkind: {failure['kind']}\n"
        f"assertion message: {failure['message']}\n\ntraceback:\n{failure['traceback']}\n\n"
        f"test source:\n{failure['test_source']}\n\n{evidence}\n</failure>"
    )
    return scrub(body)


def validate(answer: dict) -> None:
    """Small hand-written check of the schema, so the bot has no extra dependency."""
    for key in SCHEMA["required"]:
        if key not in answer:
            raise ValueError(f"missing field {key!r}")
    for key, rule in SCHEMA["properties"].items():
        value = answer[key]
        if "enum" in rule and value not in rule["enum"]:
            raise ValueError(f"{key} must be one of {rule['enum']}, got {value!r}")
        if rule.get("type") == "string" and not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        if rule.get("type") == "array" and not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
            raise ValueError(f"{key} must be a list of strings")
    if answer["fix_target"] == "none" and answer["patch"]:
        raise ValueError("patch given but fix_target is none")
    if answer["confidence"] == "low" and answer["patch"]:
        raise ValueError("low confidence must not come with a patch")


def parse_answer(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("no JSON object in the answer")
    answer = json.loads(match.group(0))
    validate(answer)
    return answer


def diagnose(failure: dict, pr: dict, client, *, model: str | None = None) -> dict:
    """Ask the model; retry once if the answer is not valid. Never raises: a bad answer becomes a clear non-answer."""
    system = (HERE / "prompt.md").read_text()
    message = build_message(failure, pr)
    messages = [{"role": "user", "content": message}]
    last_error = ""
    for _ in range(2):
        try:
            reply = client.messages.create(model=model or os.environ.get("TRIAGE_MODEL", DEFAULT_MODEL),
                                           max_tokens=MAX_OUTPUT_TOKENS, system=system, messages=messages)
            text = "".join(block.text for block in reply.content if getattr(block, "type", "") == "text")
            answer = parse_answer(text)
            answer["source"] = "model"
            return answer
        except Exception as error:  # noqa: BLE001 - network, API and parsing errors all end the same way
            last_error = f"{type(error).__name__}: {error}"
            messages = [messages[0], {"role": "assistant", "content": "(invalid)"},
                        {"role": "user", "content": f"That answer was rejected ({last_error}). Answer again with only the JSON object."}]
    return {"category": None, "fix_target": "none", "root_cause": f"The model gave no usable answer ({last_error}).",
            "evidence": [], "patch": "", "confidence": "low", "source": "error"}
