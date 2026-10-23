"""When an emulator test fails we need the evidence: screenshot, page source and logcat."""
import pytest
from harness import save_failure_artifacts

pytestmark = pytest.mark.unit


class WorkingSession:
    page_source = "<hierarchy><node text='97'/></hierarchy>"

    def save_screenshot(self, path):
        open(path, "wb").write(b"png-bytes")

    def get_log(self, name):
        assert name == "logcat"
        return [{"timestamp": 1, "level": "ERROR", "message": "boom"}]


class BrokenSession:
    @property
    def page_source(self):
        raise RuntimeError("session is gone")

    def save_screenshot(self, path):
        raise RuntimeError("session is gone")

    def get_log(self, name):
        raise RuntimeError("session is gone")


def test_saves_screenshot_page_source_and_logcat(tmp_path):
    folder = save_failure_artifacts(WorkingSession(), "test_something", root=tmp_path)

    assert (folder / "screenshot.png").read_bytes() == b"png-bytes"
    assert "text='97'" in (folder / "page_source.xml").read_text()
    assert "ERROR boom" in (folder / "logcat.txt").read_text()


def test_a_dead_session_does_not_raise_and_leaves_notes_instead(tmp_path):
    folder = save_failure_artifacts(BrokenSession(), "test_something", root=tmp_path)  # must not raise

    notes = sorted(p.name for p in folder.glob("*.error.txt"))
    assert notes == ["logcat.txt.error.txt", "page_source.xml.error.txt", "screenshot.png.error.txt"]
    assert "session is gone" in (folder / "screenshot.png.error.txt").read_text()


def test_folder_name_is_safe_for_parametrized_test_names(tmp_path):
    folder = save_failure_artifacts(WorkingSession(), "test_scores[good_night]", root=tmp_path)

    assert folder.name == "test_scores_good_night_"
    assert folder.parent == tmp_path
