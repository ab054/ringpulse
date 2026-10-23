"""The test selector: which layers each kind of change runs, and the safety rules that override the map."""
import pytest

from ci import select_tests as st

pytestmark = pytest.mark.unit

RULES = st.load_map()


def pick(*files, **kw):
    return st.select(list(files), RULES, **kw)


def test_docs_only_change_runs_nothing():
    sel = pick("README.md", "docs/test-plan.md")
    assert sel.layers == () and not sel.run_mobile and not sel.backend_layers
    assert sel.run_all_reason is None


def test_scoring_change_runs_scoring_related_layers_including_the_emulator():
    sel = pick("api/scoring.py")
    assert sel.layers == ("unit", "data", "api", "e2e")
    assert sel.run_mobile


def test_android_change_runs_only_the_emulator_layer():
    sel = pick("app/src/main/java/com/ringpulse/app/TodayScreen.kt")
    assert sel.layers == ("e2e",)
    assert sel.backend_layers == ()


def test_union_across_files():
    sel = pick("tests/sync/test_sync_faults.py", "tests/unit/test_scoring.py")
    assert sel.layers == ("unit", "sync")
    assert not sel.run_mobile


def test_the_first_matching_rule_wins_so_specific_rules_can_narrow_general_ones():
    assert "sync" not in pick("api/scoring.py").layers      # api/* would add sync; the scoring rule comes first
    assert "sync" in pick("api/db.py").layers               # no specific rule: falls to api/*


def test_unknown_file_runs_everything_and_says_which_file():
    sel = pick("README.md", "tools/new_script.sh")
    assert sel.layers == st.ALL_LAYERS
    assert "tools/new_script.sh" in sel.run_all_reason
    assert sel.files["tools/new_script.sh"][0] is None


@pytest.mark.parametrize("event", ["push", "schedule", "workflow_dispatch"])
def test_only_pull_requests_may_run_a_subset(event):
    sel = pick("README.md", event=event)
    assert sel.layers == st.ALL_LAYERS and event in sel.run_all_reason


def test_run_all_label_overrides_the_map():
    sel = pick("README.md", labels=(st.RUN_ALL_LABEL,))
    assert sel.layers == st.ALL_LAYERS


def test_failed_or_empty_diff_runs_everything():
    assert st.select([], RULES, diff_failed=True).layers == st.ALL_LAYERS
    assert st.select([], RULES).layers == st.ALL_LAYERS


def test_shared_test_plumbing_and_the_pipeline_run_everything():
    for path in ("tests/conftest.py", "pytest.ini", "requirements-dev.txt", ".github/workflows/ci.yml"):
        assert pick(path).layers == st.ALL_LAYERS, path


def test_every_rule_uses_known_layers_and_has_a_reason():
    for rule in RULES:
        assert set(rule["layers"]) <= set(st.ALL_LAYERS)
        assert rule["why"]


def test_every_tracked_file_is_covered_by_the_map():
    """If this fails, a new top-level area was added without telling the selector (it would run everything)."""
    import subprocess
    files = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.split()
    uncovered = [f for f in files if st.matching_rule(f, RULES) is None]
    assert uncovered == [], f"add these to ci/test_map.yaml: {uncovered}"


def test_summary_explains_each_file():
    text = st.summary_markdown(pick("api/scoring.py", "README.md"))
    assert "`api/scoring.py`" in text and "`README.md`" in text and "Emulator job: yes" in text


def test_cli_writes_outputs(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    st.main(["--event", "pull_request", "--files", "tests/sync/test_sync_faults.py"])

    assert out.read_text().splitlines() == ["layers=sync", "backend=true", "backend_markers=sync", "mobile=false"]
