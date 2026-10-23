import itertools

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from ring_sim import RingSimulator, load_night

LAYERS = ("unit", "data", "api", "sync", "e2e")


def pytest_collection_modifyitems(items):
    """Every test must carry a layer marker, so CI and test selection can pick layers."""
    for item in items:
        if not any(item.get_closest_marker(layer) for layer in LAYERS):
            raise pytest.UsageError(f"{item.nodeid} has no layer marker (one of: {', '.join(LAYERS)})")


@pytest.fixture
def make_client(tmp_path):
    """Factory: each call returns a new API with its own empty database."""
    counter = itertools.count()
    return lambda: TestClient(create_app(str(tmp_path / f"api-{next(counter)}.db")))


@pytest.fixture
def client(make_client):
    return make_client()


@pytest.fixture
def ring():
    """Factory: ring('good_night') -> a simulator holding that fixture night."""
    return lambda name: RingSimulator(load_night(name))


@pytest.fixture
def insights(client):
    """insights(night_id) -> the parsed GET /nights/{id} body, asserting it succeeded."""

    def get(night_id):
        response = client.get(f"/nights/{night_id}")
        assert response.status_code == 200, response.text
        return response.json()

    return get
