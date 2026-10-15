import json
import os
from pathlib import Path

import pytest

from fakes import (ANON_KEY, APP_ID, CLIENT_ID, CLIENT_SECRET, DEMO, JWT_SECRET, PRIVATE_PEM, SERVICE_KEY,
                   SUPABASE_HOST, World)

ROOT = Path(__file__).resolve().parents[2]

# Set every variable explicitly so values from a real backend/.env can never leak into tests
os.environ.update({
    "APC_SKIP_DOTENV": "1",
    "SUPABASE_URL": f"https://{SUPABASE_HOST}",
    "SUPABASE_ANON_KEY": ANON_KEY,
    "SUPABASE_SERVICE_KEY": SERVICE_KEY,
    "SUPABASE_JWT_SECRET": JWT_SECRET,
    "APP_URL": "http://localhost:5173",
    "PORT": "5173",   # desktop mode: the engine answers only to its own port (the test clients use localhost:5173)
    "COOKIE_SECURE": "0",
    "GITHUB_APP_ID": APP_ID,
    "GITHUB_APP_SLUG": "apc-test",
    "GITHUB_APP_CLIENT_ID": CLIENT_ID,
    "GITHUB_APP_CLIENT_SECRET": CLIENT_SECRET,
    "GITHUB_APP_PRIVATE_KEY": PRIVATE_PEM.replace("\n", "\\n"),
    "GITHUB_APP_PRIVATE_KEY_PATH": "",
    "GITHUB_BLOCKED_ACCOUNTS": "official-hackathon-org",
})
os.environ.pop("DESKTOP_MODE", None)
os.environ.pop("GITHUB_TOKEN", None)

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# Strings that must never appear in any response or log line
SECRET_MARKERS = ("ghs_", "ghu_", "ghp_", "PRIVATE KEY", CLIENT_SECRET, PRIVATE_PEM.splitlines()[1][:40], SERVICE_KEY,
                  "refresh-")


class CheckedClient(TestClient):
    """TestClient that fails the test if any response body leaks a token or key."""

    def request(self, *args, **kwargs):
        r = super().request(*args, **kwargs)
        blob = r.text + json.dumps({k: v for k, v in r.headers.items() if k.lower() != "set-cookie"})
        for marker in SECRET_MARKERS:
            assert marker not in blob, f"response leaked {marker!r}: {r.request.method} {r.request.url}"
        return r


@pytest.fixture()
def world(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SEED_DIR", str(ROOT / "data"))
    from app import auth, github_access, inventory, store, supa
    from app import github_app as gh
    from app import http as apphttp
    w = World()
    transport = httpx.MockTransport(w.handler)
    supa.TRANSPORT = transport
    supa.reset_client()
    original = apphttp.client._transport
    apphttp.client._transport = transport
    store.reset_connection()
    inventory.load.cache_clear()
    github_access._repo_cache.clear()
    gh._installation_tokens.clear()
    github_access._write_limit.hits.clear()
    auth._login_limit.hits.clear()
    auth._desktop.clear()
    auth._refreshes.clear()
    caplog.set_level("DEBUG")
    yield w
    apphttp.client._transport = original
    supa.TRANSPORT = None
    supa.reset_client()
    for record in caplog.records:
        message = record.getMessage()
        for marker in SECRET_MARKERS[:-1]:
            assert marker not in message, f"log line leaked {marker!r}: {message}"


def make_client() -> CheckedClient:
    from app.main import app
    return CheckedClient(app, base_url="http://localhost:5173")


def sign_in(c: TestClient, uid: str = DEMO) -> None:
    """Sign in through the real flow: /api/auth/login sets the PKCE cookie, and the fake Supabase treats the
    auth code as the user id, so cookies behave exactly as they would for a real GitHub sign-in."""
    c.cookies.clear()
    r = c.get("/api/auth/login", follow_redirects=False)
    assert r.status_code == 302, r.text
    r = c.get(f"/api/auth/callback?code={uid}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/", r.text


def sign_out(c: TestClient) -> None:
    assert c.post("/api/auth/logout").status_code == 200
    c.cookies.clear()


def client_as(uid: str | None) -> CheckedClient:
    c = make_client()
    if uid:
        sign_in(c, uid)
    return c


@pytest.fixture()
def client(world):
    with make_client() as c:
        yield c


@pytest.fixture(autouse=True)
def _isolate_provider_keys():
    """Provider keys live in process memory; never let one test's keys leak into another."""
    from app import github, keys
    keys.clear()
    github.clear_cache()
    yield
    keys.clear()
    github.clear_cache()
