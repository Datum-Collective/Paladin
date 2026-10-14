LOG = "May 14 13:05:11 WEB-BO-01 sshd[912]: Accepted password for www-data from 185.199.110.42 port 51544 ssh2"
SCAN = '185.199.110.42 - - [14/May/2024:13:00:01 +0000] "GET /.env HTTP/1.1" 404 153 "-" "Nikto/2.1.6"'


def setup(c):
    c.post("/api/auth/demo")
    c.post("/api/ingest", json={"format": "web_access", "lines": [SCAN]})
    return c.get("/api/fixes").json()["best_single"]["edges"]


def test_full_lifecycle_verified(client):
    edges = setup(client)
    before = client.get("/api/paths").json()["risk"]
    r = client.post("/api/remediations", json={"edges": edges, "title": "fix"}).json()
    assert r["state"] == "proposed" and "Verify" in r["runbook"] and r["ai_drafted"] is False
    rid = r["id"]
    assert client.post(f"/api/remediations/{rid}/execute").status_code == 409  # not approved
    assert client.post(f"/api/remediations/{rid}/approve").json()["state"] == "approved"
    assert client.post(f"/api/remediations/{rid}/execute").json()["state"] == "executed"
    assert client.get("/api/paths").json()["risk"] < before
    assert client.post(f"/api/remediations/{rid}/verify").json()["state"] == "verified"
    d = client.get(f"/api/remediations/{rid}").json()
    assert [a["action"] for a in d["audit"]] == ["proposed", "approved", "executed", "verified"]


def test_verify_fails_when_still_observed(client):
    c = client
    c.post("/api/auth/demo")
    c.post("/api/ingest", json={"format": "web_access", "lines": [SCAN]})
    rid = c.post("/api/remediations", json={"edges": ["scan-web"]}).json()["id"]
    c.post(f"/api/remediations/{rid}/approve")
    c.post(f"/api/remediations/{rid}/execute")
    c.post("/api/ingest", json={"format": "web_access", "lines": [SCAN]})  # attacker still active
    r = c.post(f"/api/remediations/{rid}/verify").json()
    assert r["state"] == "failed" and "still observed" in r["note"]


def test_rollback_restores_risk(client):
    edges = setup(client)
    before = client.get("/api/paths").json()["risk"]
    rid = client.post("/api/remediations", json={"edges": edges}).json()["id"]
    client.post(f"/api/remediations/{rid}/approve")
    client.post(f"/api/remediations/{rid}/execute")
    client.post(f"/api/remediations/{rid}/rollback")
    assert abs(client.get("/api/paths").json()["risk"] - before) < 1e-9


def test_validation_auth_and_isolation(client):
    assert client.get("/api/remediations").status_code == 401
    client.post("/api/auth/demo")
    assert client.post("/api/remediations", json={"edges": ["nope"]}).status_code == 422
    rid = client.post("/api/remediations", json={"edges": ["scan-web"]}).json()["id"]
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={"email": "o@b.co", "password": "longenough1"})
    assert client.get(f"/api/remediations/{rid}").status_code == 404


def test_ai_draft_used_when_available(client, monkeypatch):
    from app import ai
    monkeypatch.setattr(ai, "draft", lambda facts: "1. AI steps")
    client.post("/api/auth/demo")
    r = client.post("/api/remediations", json={"edges": ["scan-web"]}).json()
    assert r["ai_drafted"] is True and r["runbook"] == "1. AI steps"
