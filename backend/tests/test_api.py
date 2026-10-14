from conftest import sign_in
from fakes import DEMO, OTHER

LOG = ("May 14 13:05:11 WEB-BO-01 sshd[912]: Accepted password for www-data from 185.199.110.42 port 51544 ssh2")
SCAN = ('185.199.110.42 - - [14/May/2024:13:00:01 +0000] "GET /.env HTTP/1.1" 404 153 "-" "Nikto/2.1.6"')


def login(c):
    sign_in(c)


def test_requires_auth(client):
    for path in ("/api/graph", "/api/paths", "/api/fixes", "/api/me"):
        assert client.get(path).status_code == 401
    assert client.post("/api/ingest", json={"format": "linux_auth", "lines": [LOG]}).status_code == 401
    assert client.get("/health").json() == {"status": "ok"}


def test_password_and_demo_sign_in_are_gone(client):
    """GitHub is the only way in: no password endpoints and no shared demo account."""
    for path in ("/api/auth/register", "/api/auth/demo", "/api/auth/local"):
        assert client.post(path, json={"email": "a@b.co", "password": "longenough1"}).status_code in (404, 405)
    assert client.post("/api/auth/login", json={"email": "demo@example.com", "password": "x"}).status_code == 405
    assert client.get("/api/me").status_code == 401


def test_ingest_raises_risk_and_fix_lowers_it(client):
    login(client)
    base = client.get("/api/paths").json()
    r = client.post("/api/ingest", json={"format": "linux_auth", "lines": [LOG, "garbage"]}).json()
    assert r["accepted"] == 1 and r["rejected"] == 1
    client.post("/api/ingest", json={"format": "web_access", "lines": [SCAN]})
    after = client.get("/api/paths").json()
    assert after["risk"] > base["risk"]
    top = after["paths"][0]
    assert top["hops"][0]["technique"] and top["narrative"]
    fx = client.get("/api/fixes").json()
    assert fx["cheapest_cut"]["edges"]
    res = client.post("/api/fixes/apply", json={"edges": fx["cheapest_cut"]["edges"]}).json()
    assert res["risk"] < after["risk"]


def test_unknown_format_and_keys(client):
    login(client)
    assert client.post("/api/ingest", json={"format": "nope", "lines": ["x"]}).status_code == 422
    key = client.post("/api/keys", json={"label": "t"}).json()["key"]
    client.post("/api/auth/logout")
    r = client.post("/api/ingest", headers={"X-API-Key": key}, json={"format": "linux_auth", "lines": [LOG]})
    assert r.status_code == 200 and r.json()["accepted"] == 1
    assert client.post("/api/ingest", headers={"X-API-Key": "apc_bad"}, json={"format": "linux_auth", "lines": [LOG]}).status_code == 401


def test_workspaces_isolated(client):
    login(client)
    client.post("/api/ingest", json={"format": "linux_auth", "lines": [LOG]})
    client.post("/api/auth/logout")
    sign_in(client, OTHER)
    assert client.get("/api/graph").json()["events"] == 0


def test_unknown_edge_rejected(client):
    login(client)
    assert client.post("/api/fixes/apply", json={"edges": ["nope"]}).status_code == 422


def test_me_is_the_github_profile(client):
    sign_in(client)
    me = client.get("/api/me").json()
    assert me["login"] == "demo-gh" and me["id"] == DEMO and me["avatar_url"].startswith("https://")


def test_empty_workspace_reports_no_risk(client):
    sign_in(client)
    g = client.get("/api/graph").json()
    assert g["events"] == 0 and g["risk"] == 0 and g["severity"] == "LOW"
    assert client.get("/api/paths").json()["paths"] == []
    assert client.get("/api/fixes").json()["cheapest_cut"] is None


def test_play_sample_scenario_produces_ranked_path(client):
    login(client)
    status = client.get("/api/simulate/status").json()
    assert status["total"] > 0

    replay = client.post("/api/simulate/start").json()
    while not replay["done"]:
        replay = client.post("/api/simulate/step?n=500").json()

    paths = client.get("/api/paths").json()["paths"]
    assert replay["position"] == replay["total"] == status["total"]
    assert paths and paths[0]["risk"] > 0
