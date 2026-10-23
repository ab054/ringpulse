import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from ring_sim import RingSimulator, load_night


@pytest.fixture
def client(tmp_path):
    """A fresh API with its own empty database for every test."""
    return TestClient(create_app(str(tmp_path / "test.db")))


@pytest.fixture
def ring():
    """Factory: ring('good_night') -> a simulator holding that fixture night."""
    return lambda name: RingSimulator(load_night(name))
