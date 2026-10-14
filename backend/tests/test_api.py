LOG = ("May 14 13:05:11 WEB-BO-01 sshd[912]: Accepted password for www-data from 185.199.110.42 port 51544 ssh2")
SCAN = ('185.199.110.42 - - [14/May/2024:13:00:01 +0000] "GET /.env HTTP/1.1" 404 153 "-" "Nikto/2.1.6"')


def login(c):
    r = c.post("/api/auth/login", json={"email": "demo@example.com", "password": "demo-password"})
    assert r.status_code == 200


def test_requires_auth(client):
    for path in ("/api/graph", "/api/paths", "/api/fixes", "/api/me"):
        assert client.get(path).status_code == 401
    assert client.post("/api/ingest", json={"format": "linux_auth", "lines": [LOG]}).status_code == 401
    assert client.get("/health").json() == {"status": "ok"}


def test_bad_login_and_register(client):
    assert client.post("/api/auth/login", json={"email": "demo@example.com", "password": "x"}).status_code == 401
    assert client.post("/api/auth/register", json={"email": "bad", "password": "longenough1"}).status_code == 422
    r = client.post("/api/auth/register", json={"email": "a@b.co", "password": "longenough1"})
    assert r.status_code == 200 and client.get("/api/me").json()["email"] == "a@b.co"


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
    client.post("/api/auth/register", json={"email": "other@b.co", "password": "longenough1"})
    assert client.get("/api/graph").json()["events"] == 0


def test_unknown_edge_rejected(client):
    login(client)
    assert client.post("/api/fixes/apply", json={"edges": ["nope"]}).status_code == 422
