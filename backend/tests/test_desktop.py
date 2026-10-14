"""Desktop mode: loopback-only local account gated by a per-launch token, plus the public /api/config."""
import pytest

TOKEN = "t" * 40


def test_config_is_public_and_reports_web_mode(client):
    c = client.get("/api/config").json()
    assert c["desktop"] is False
    assert set(c) >= {"desktop", "demo", "ai", "github", "version"}


def test_local_login_disabled_outside_desktop_mode(client):
    r = client.post("/api/auth/local", headers={"X-Desktop-Token": TOKEN})
    assert r.status_code == 404


@pytest.fixture()
def desktop(client, monkeypatch):
    monkeypatch.setenv("DESKTOP_MODE", "1")
    monkeypatch.setenv("APC_DESKTOP_TOKEN", TOKEN)
    return client


def test_config_reports_desktop(desktop):
    assert desktop.get("/api/config").json()["desktop"] is True


def test_local_login_requires_token(desktop):
    assert desktop.post("/api/auth/local").status_code == 403
    assert desktop.post("/api/auth/local", headers={"X-Desktop-Token": "wrong"}).status_code == 403
    assert desktop.get("/api/me").status_code == 401


def test_local_login_opens_a_session_and_keeps_one_workspace(desktop):
    r = desktop.post("/api/auth/local", headers={"X-Desktop-Token": TOKEN})
    assert r.status_code == 200
    first = desktop.get("/api/me").json()["email"]
    desktop.post("/api/auth/logout")
    desktop.post("/api/auth/local", headers={"X-Desktop-Token": TOKEN})
    assert desktop.get("/api/me").json()["email"] == first


def test_local_login_does_not_wipe_existing_data(desktop):
    desktop.post("/api/auth/local", headers={"X-Desktop-Token": TOKEN})
    line = ("May 14 13:05:11 WEB-BO-01 sshd[912]: Accepted password for www-data "
            "from 185.199.110.42 port 51544 ssh2")
    assert desktop.post("/api/ingest", json={"format": "linux_auth", "lines": [line]}).json()["accepted"] == 1
    desktop.post("/api/auth/logout")
    desktop.post("/api/auth/local", headers={"X-Desktop-Token": TOKEN})
    assert desktop.get("/api/graph").json()["events"] == 1


def test_desktop_token_missing_from_env_never_authenticates(client, monkeypatch):
    monkeypatch.setenv("DESKTOP_MODE", "1")
    monkeypatch.delenv("APC_DESKTOP_TOKEN", raising=False)
    assert client.post("/api/auth/local", headers={"X-Desktop-Token": ""}).status_code == 403
