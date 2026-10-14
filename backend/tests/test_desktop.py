"""Desktop mode: GitHub sign-in runs in the system browser and the app window claims the session with the
per-launch token; the public /api/config; no server secrets in the desktop engine."""
from urllib.parse import parse_qs, urlparse

import pytest

from conftest import make_client
from fakes import ALICE, BOB, DEMO

TOKEN = "t" * 40
LOG = ("May 14 13:05:11 WEB-BO-01 sshd[912]: Accepted password for www-data from 185.199.110.42 port 51544 ssh2")


def test_config_is_public_and_reports_web_mode(client):
    c = client.get("/api/config").json()
    assert c["desktop"] is False and c["auth"] == "github" and c["github_mode"] == "app"
    assert set(c) >= {"desktop", "auth", "ai", "github", "version"}


@pytest.mark.parametrize("path", ["/api/auth/desktop/start", "/api/auth/desktop/claim"])
def test_desktop_sign_in_is_disabled_outside_desktop_mode(client, path):
    assert client.post(path, headers={"X-Desktop-Token": TOKEN}).status_code == 404


@pytest.fixture()
def desktop(client, monkeypatch):
    monkeypatch.setenv("DESKTOP_MODE", "1")
    monkeypatch.setenv("APC_DESKTOP_TOKEN", TOKEN)
    monkeypatch.setenv("PORT", "8765")
    return client


def start(app_window) -> str:
    r = app_window.post("/api/auth/desktop/start", headers={"X-Desktop-Token": TOKEN})
    assert r.status_code == 200
    url = urlparse(r.json()["url"])
    assert url.scheme == "http" and url.netloc == "127.0.0.1:8765" and url.path == "/api/auth/login"
    return f"{url.path}?{url.query}"


def browser_signs_in(login_path: str, uid: str):
    """The system browser: a separate cookie jar from the app window."""
    browser = make_client()
    r = browser.get(login_path, follow_redirects=False)
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["redirect_to"] == ["http://127.0.0.1:8765/api/auth/callback"] and q["prompt"] == ["select_account"]
    r = browser.get(f"/api/auth/callback?code={uid}", follow_redirects=False)
    return browser, r


def claim(app_window, token=TOKEN):
    return app_window.post("/api/auth/desktop/claim", headers={"X-Desktop-Token": token} if token else {})


def sign_in_desktop(app_window, uid=DEMO):
    browser, r = browser_signs_in(start(app_window), uid)
    assert r.status_code == 200 and "signed in" in r.text
    assert claim(app_window).json() == {"signed_in": True}


def test_config_reports_desktop(desktop):
    c = desktop.get("/api/config").json()
    assert c["desktop"] is True and c["github_mode"] == "token"


def test_full_desktop_sign_in(desktop):
    assert desktop.get("/api/me").status_code == 401
    assert claim(desktop).json() == {"signed_in": False}           # nothing to claim yet
    browser, r = browser_signs_in(start(desktop), ALICE)
    assert r.status_code == 200 and "signed in" in r.text.lower()
    # the browser tab never gets a session
    assert not {"sb_access", "sb_refresh"} & set(browser.cookies.keys())
    assert browser.get("/api/me").status_code == 401
    assert claim(desktop).json() == {"signed_in": True}
    assert desktop.get("/api/me").json()["login"] == "alice-gh"
    assert claim(desktop).json() == {"signed_in": False}           # single use


def test_start_and_claim_require_the_launch_token(desktop):
    assert desktop.post("/api/auth/desktop/start").status_code == 403
    assert desktop.post("/api/auth/desktop/start", headers={"X-Desktop-Token": "wrong"}).status_code == 403
    login_path = start(desktop)
    browser_signs_in(login_path, BOB)
    assert claim(desktop, token=None).status_code == 403
    assert claim(desktop, token="wrong").status_code == 403
    assert desktop.get("/api/me").status_code == 401


def test_a_web_page_cannot_start_or_finish_a_desktop_sign_in(desktop):
    """Without a nonce from desktop/start (which needs the launch token), the login and callback refuse."""
    attacker = make_client()
    assert attacker.get("/api/auth/login", follow_redirects=False).status_code == 404
    assert attacker.get("/api/auth/login?desktop=guessed", follow_redirects=False).status_code == 404
    # a callback with the attacker's own code but no sign-in in progress parks nothing
    attacker.cookies.set("pkce_verifier", "v", path="/api/auth")
    attacker.cookies.set("desktop_signin", "guessed", path="/api/auth")
    assert attacker.get(f"/api/auth/callback?code={BOB}", follow_redirects=False).status_code == 400
    assert claim(desktop).json() == {"signed_in": False}


def test_sign_in_link_is_single_use(desktop):
    login_path = start(desktop)
    browser_signs_in(login_path, ALICE)
    browser = make_client()
    assert browser.get(login_path, follow_redirects=False).status_code == 404


def test_desktop_data_is_the_accounts_data(desktop):
    """Data lives in Supabase per account, so signing out and back in shows the same workspace."""
    sign_in_desktop(desktop)
    assert desktop.post("/api/ingest", json={"format": "linux_auth", "lines": [LOG]}).json()["accepted"] == 1
    assert desktop.post("/api/auth/logout").status_code == 200
    assert desktop.get("/api/graph").status_code == 401
    sign_in_desktop(desktop)
    assert desktop.get("/api/graph").json()["events"] == 1


def test_desktop_never_uses_the_service_key_or_github_app(desktop, world):
    sign_in_desktop(desktop)
    desktop.get("/api/workspaces")
    desktop.post("/api/ingest", json={"format": "linux_auth", "lines": [LOG]})
    assert desktop.get("/api/github/install-url").status_code == 503
    assert not [r for r in world.db.requests if r[0] == "service"]


def test_desktop_token_missing_from_env_never_authenticates(client, monkeypatch):
    monkeypatch.setenv("DESKTOP_MODE", "1")
    monkeypatch.delenv("APC_DESKTOP_TOKEN", raising=False)
    assert client.post("/api/auth/desktop/start", headers={"X-Desktop-Token": ""}).status_code == 403
    assert client.post("/api/auth/desktop/claim", headers={"X-Desktop-Token": ""}).status_code == 403
