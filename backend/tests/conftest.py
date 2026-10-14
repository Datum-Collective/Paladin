import os
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SEED_DIR", str(ROOT / "data"))
    monkeypatch.setenv("DEMO_USER", "demo@example.com")
    monkeypatch.setenv("DEMO_PASSWORD", "demo-password")
    monkeypatch.setenv("COOKIE_SECURE", "0")
    from app import store, inventory
    store.reset_connection()
    inventory.load.cache_clear()
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c
    store.reset_connection()


@pytest.fixture(autouse=True)
def _isolate_provider_keys():
    """Provider keys live in process memory; never let one test's keys leak into another."""
    from app import github, keys
    keys.clear()
    github.clear_cache()
    yield
    keys.clear()
    github.clear_cache()
