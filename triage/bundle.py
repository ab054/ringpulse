"""Step 1, plain Python: turn JUnit reports into one failure bundle per failed test. No model involved."""
from __future__ import annotations

import ast
import re
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_TRACE = 3000
MAX_SOURCE = 3000
MAX_LOG = 2000


def _clip(text: str, limit: int, keep_end: bool = False) -> str:
    if len(text) <= limit:
        return text
    return ("...[cut]\n" + text[-limit:]) if keep_end else (text[:limit] + "\n...[cut]")


def locate(classname: str, root: Path) -> tuple[str, str | None]:
    """'tests.api.test_x.TestY' -> ('tests/api/test_x.py', 'TestY'): the longest prefix that is a file."""
    parts = classname.split(".")
    for end in range(len(parts), 0, -1):
        candidate = "/".join(parts[:end]) + ".py"
        if (root / candidate).is_file():
            return candidate, ".".join(parts[end:]) or None
    return "/".join(parts) + ".py", None


def function_source(path: Path, name: str) -> str:
    base = name.split("[")[0]
    try:
        text = path.read_text()
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == base:
                lines = text.splitlines()
                start = min([node.lineno] + [d.lineno for d in node.decorator_list])
                return "\n".join(lines[start - 1:node.end_lineno])
    except (OSError, SyntaxError):
        pass
    return ""


def parse_junit(path: Path, kind: str, root: Path) -> list[dict]:
    failures = []
    for case in ET.parse(path).getroot().iter("testcase"):
        problem = case.find("failure")
        if problem is None:
            problem = case.find("error")
        if problem is None:
            continue
        file, owner = locate(case.get("classname", ""), root)
        name = case.get("name", "")
        nodeid = "::".join(p for p in (file, owner and owner.replace(".", "::"), name) if p)
        failures.append({
            "id": nodeid,
            "kind": kind,
            "file": file,
            "name": name,
            "message": _clip(problem.get("message") or "", 800),
            "traceback": _clip((problem.text or "").strip(), MAX_TRACE, keep_end=True),
            "test_source": _clip(function_source(root / file, name), MAX_SOURCE),
            "evidence_files": {},
        })
    return failures


def attach_e2e_artifacts(failures: list[dict], artifacts_dir: Path) -> None:
    """Page source and logcat saved by the emulator harness (folder name = sanitised test name)."""
    for failure in failures:
        if failure["kind"] != "e2e":
            continue
        folder = artifacts_dir / re.sub(r"[^A-Za-z0-9_.-]+", "_", failure["name"])
        for filename, keep_end in (("page_source.xml", False), ("logcat.txt", True)):
            path = folder / filename
            if path.is_file():
                failure["evidence_files"][filename] = _clip(path.read_text(errors="replace"), MAX_LOG, keep_end)


def build_bundle(junit: dict[str, Path], root: Path, *, artifacts_dir: Path | None = None) -> list[dict]:
    """junit maps a kind ('backend', 'e2e') to its JUnit file; missing files are skipped."""
    failures: list[dict] = []
    for kind, path in junit.items():
        if Path(path).is_file():
            failures += parse_junit(Path(path), kind, root)
    if artifacts_dir:
        attach_e2e_artifacts(failures, artifacts_dir)
    return failures
