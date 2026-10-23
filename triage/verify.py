"""Step 4, plain Python: try the suggested patch in a scratch copy and re-run only the failed tests.

The model's patch is never trusted: it is checked against rules first, applied to a throw-away copy,
and counted as a fix only if the previously failing tests pass there."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FORBIDDEN_PREFIXES = (".github/", "ci/", "triage/", "requirements", ".git/")
TEST_PREFIXES = ("tests/", "fixtures/")
IGNORE = shutil.ignore_patterns(".git", ".venv", "venv", "build", ".gradle", "node_modules", "__pycache__", ".pytest_cache", "artifacts")

VERIFIED, DID_NOT_HELP, NOT_ATTEMPTED, REJECTED = "fix verified", "fix did not help", "not attempted", "patch rejected"


def patch_files(patch: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r"^\+\+\+ b/(\S+)", patch, re.M)] + \
           [m.group(1) for m in re.finditer(r"^--- a/(\S+)", patch, re.M)]


def check_patch(patch: str, fix_target: str) -> str | None:
    """A reason to reject the patch, or None when it is acceptable."""
    files = set(patch_files(patch))
    if not files:
        return "the patch changes no file"
    if re.search(r"^\+\+\+ /dev/null", patch, re.M):
        return "the patch deletes a file"
    for path in files:
        if path.startswith("/") or ".." in path.split("/"):
            return f"unsafe path {path}"
        if path.startswith(FORBIDDEN_PREFIXES):
            return f"{path} is off limits for the bot"
        is_test = path.startswith(TEST_PREFIXES)
        if fix_target == "app" and is_test:
            return f"an app fix must not edit tests ({path})"
        if fix_target == "test" and not is_test:
            return f"a test fix must only edit tests or fixtures ({path})"
    return None


def verify(patch: str, fix_target: str, test_ids: list[str], repo: Path, *, kind: str = "backend", timeout: int = 300) -> tuple[str, str]:
    """Returns (status, detail)."""
    if not patch:
        return NOT_ATTEMPTED, "no patch"
    if kind != "backend":
        return NOT_ATTEMPTED, "emulator tests cannot be re-run in the triage job"
    reason = check_patch(patch, fix_target)
    if reason:
        return REJECTED, reason
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "repo"
        shutil.copytree(repo, scratch, ignore=IGNORE)
        applied = subprocess.run(["git", "apply", "--whitespace=nowarn", "-"], input=patch, text=True, cwd=scratch, capture_output=True)
        if applied.returncode:
            return REJECTED, "the patch does not apply: " + applied.stderr.strip()[:300]
        try:
            run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *test_ids],
                                 cwd=scratch, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return DID_NOT_HELP, "the re-run timed out"
        tail = "\n".join(run.stdout.strip().splitlines()[-3:])
        return (VERIFIED if run.returncode == 0 else DID_NOT_HELP), tail
