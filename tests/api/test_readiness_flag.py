import pytest

from api.main import create_app

pytestmark = pytest.mark.api


def test_unknown_formula_fails_at_startup(monkeypatch, tmp_path):
    monkeypatch.setenv("RINGPULSE_READINESS_FORMULA", "v3")
    with pytest.raises(ValueError, match="v3"):
        create_app(str(tmp_path / "t.db"))


@pytest.mark.parametrize("formula", ["v1", "v2"])
def test_known_formulas_start(monkeypatch, tmp_path, formula):
    monkeypatch.setenv("RINGPULSE_READINESS_FORMULA", formula)
    create_app(str(tmp_path / "t.db"))
