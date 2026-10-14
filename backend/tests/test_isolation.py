"""Bug-bounty threat model for the merged app: a signed-in tester must never reach another user's workspaces,
scans, keys or GitHub repos, and the server's own credentials must never act for them."""
import time

import httpx
import pytest

from app import github, harness, keys
from conftest import client_as
from fakes import ALICE, BOB, DEMO

LOG = ("May 14 13:05:11 WEB-BO-01 sshd[912]: Accepted password for www-data from 185.199.110.42 port 51544 ssh2")


def link(world, uid, installation_id):
    world.db.add("github_installations", {
        "user_id": uid, "installation_id": installation_id,
        "github_account_login": world.gh.installations[installation_id]["account"]["login"]})


@pytest.fixture
def alice_data(world):
    """Alice has a workspace with events, a remediation, a code scan and a finished scan job."""
    alice = client_as(ALICE)
    ws = alice.get("/api/workspaces").json()["active"]
    alice.post("/api/ingest", json={"format": "linux_auth", "lines": [LOG]})
    edges = alice.get("/api/fixes").json()["cheapest_cut"]["edges"]
    rid = alice.post("/api/remediations", json={"edges": edges, "title": "Alice's fix"}).json()["id"]
    alice.post("/api/codescan", json={"repo": "alice/app", "files": [{"path": "a.py", "content": "eval(input())\n"}]})
    jid = world.db.add("jobs", {"ws": ws, "user_id": ALICE, "repo_url": "alice-gh/demo", "state": "ready",
                                "created": time.time(), "updated": time.time(), "diff": "ALICE-SECRET-DIFF",
                                "fixes": [{"file": "a.py"}]})
    key = alice.post("/api/keys", json={"label": "alice"}).json()["key"]
    key_id = alice.get("/api/keys").json()["keys"][0]["id"]
    return {"client": alice, "ws": ws, "rid": rid, "jid": jid, "key": key, "key_id": key_id}


def test_another_user_reaches_nothing_by_id(alice_data, world):
    a = alice_data
    bob = client_as(BOB)
    ws, rid, jid = a["ws"], a["rid"], a["jid"]
    pin = {"X-Workspace": str(ws)}
    # Bob pinning Alice's workspace is ignored: he sees his own (empty) one
    for path in ("/api/graph", "/api/events", "/api/codescan", "/api/activity", "/api/remediations",
                 "/api/harness/jobs", "/api/paths", "/api/timeline"):
        body = bob.get(path, headers=pin).text
        assert "Alice" not in body and "alice" not in body.lower().replace("alice-gh", ""), path
    assert bob.get("/api/graph", params={"ws": ws}).json()["events"] == 0
    # ids of Alice's things are 404 for Bob
    for method, path in [("GET", f"/api/remediations/{rid}"), ("POST", f"/api/remediations/{rid}/approve"),
                         ("POST", f"/api/remediations/{rid}/rollback"), ("GET", f"/api/harness/jobs/{jid}"),
                         ("GET", f"/api/harness/jobs/{jid}/patch"), ("GET", f"/api/harness/jobs/{jid}/file?path=a.py"),
                         ("POST", f"/api/harness/jobs/{jid}/pr"), ("POST", f"/api/workspaces/{ws}/open"),
                         ("PATCH", f"/api/workspaces/{ws}"), ("DELETE", f"/api/workspaces/{ws}"),
                         ("DELETE", f"/api/keys/{a['key_id']}")]:
        r = bob.request(method, path, json={"name": "pwned"})
        assert r.status_code in (404, 409), (method, path, r.status_code)
        assert "ALICE-SECRET-DIFF" not in r.text
    # Bob's attempts changed nothing of Alice's
    alice = a["client"]
    assert alice.get("/api/graph").json()["events"] == 1
    assert [w["name"] for w in alice.get("/api/workspaces").json()["workspaces"]] == ["Workspace"]
    assert alice.get(f"/api/remediations/{rid}").json()["state"] == "proposed"
    assert alice.get("/api/keys").json()["keys"][0]["revoked_at"] is None


def test_bob_cannot_write_into_alices_workspace(alice_data):
    bob = client_as(BOB)
    pin = {"X-Workspace": str(alice_data["ws"])}
    bob.post("/api/ingest", headers=pin, json={"format": "linux_auth", "lines": [LOG] * 3})
    bob.post("/api/simulate/reset", headers=pin)
    bob.delete("/api/codescan", headers=pin)
    alice = alice_data["client"]
    assert alice.get("/api/graph").json()["events"] == 1
    assert alice.get("/api/codescan").json()["scanned"] is True


def test_server_github_token_is_never_used_on_the_web(client, world, monkeypatch):
    """A token in the server environment would let every user browse whatever it can see."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_server_owned_token")
    seen = []

    def spy(req):
        seen.append(req.headers.get("authorization"))
        return httpx.Response(404, json={"message": "Not Found"})

    monkeypatch.setattr(github, "TRANSPORT", httpx.MockTransport(spy))
    c = client_as(BOB)
    assert keys.get("GITHUB_TOKEN") is None
    assert c.get("/api/repos/suggest", params={"q": ""}).status_code == 200
    assert c.post("/api/repos/resolve", json={"query": "alice-gh/demo"}).status_code == 404
    assert c.post("/api/workspaces/import", json={"query": "alice-gh/demo"}).status_code == 404
    assert seen and all(h is None for h in seen)          # public lookups only, no credentials at all
    assert c.get("/api/config").json()["github_mode"] == "app"


def test_scan_clone_token_is_read_only_and_only_for_the_users_own_repo(client, world, monkeypatch):
    link(world, ALICE, 1001)
    started = []
    monkeypatch.setattr(harness, "start",
                        lambda ws, url, token=None: (started.append((url, token)), {"id": 1, "state": "queued"})[1])
    alice = client_as(ALICE)
    assert alice.post("/api/workspaces/import", json={"query": "alice-gh/demo"}).status_code == 200
    (url, token), = started
    assert url == "https://github.com/alice-gh/demo" and token.startswith("ghs_")
    assert world.gh.inst_tokens[token] == (1001, 5001, {"contents": "read"})
    # Bob asking for Alice's private repo gets no token (and the public lookup finds nothing)
    monkeypatch.setattr(github, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(404, json={})))
    bob = client_as(BOB)
    assert bob.post("/api/harness/jobs", json={"repo_url": "https://github.com/alice-gh/demo"}).status_code == 200
    assert started[-1] == ("https://github.com/alice-gh/demo", None)


def test_pull_request_only_for_the_users_own_installation(alice_data, world, tmp_path):
    link(world, BOB, 1002)        # Bob has his own installation, but not Alice's repo
    bob = client_as(BOB)
    ws = bob.get("/api/workspaces").json()["active"]
    jid = world.db.add("jobs", {"ws": ws, "user_id": BOB, "repo_url": "alice-gh/demo", "state": "ready",
                                "created": time.time(), "updated": time.time(), "fixes": [{"file": "a.py"}]})
    d = harness.data_root() / str(jid) / "repo"
    d.mkdir(parents=True)
    (d / "a.py").write_text("pwned = True\n")
    r = bob.post(f"/api/harness/jobs/{jid}/pr")
    assert r.status_code == 409 and "github app" in r.json()["detail"].lower()
    _, repo = world.gh.repo_by_name("alice-gh/demo")
    assert "fixes" not in repo["branches"] and repo["pulls"] == [] and not world.gh.touched_repo("alice-gh/demo")


def test_scan_errors_never_contain_the_clone_token(client, world, monkeypatch):
    link(world, ALICE, 1001)

    def failing_git(args, **kw):
        raise RuntimeError(f"git clone failed: could not read from https://x-access-token:{kw.get('token')}@github.com")

    monkeypatch.setattr(harness, "_git", failing_git)
    alice = client_as(ALICE)
    job = alice.post("/api/workspaces/import", json={"query": "alice-gh/demo"}).json()["job"]
    harness.wait(job["id"], 30)
    got = alice.get(f"/api/harness/jobs/{job['id']}").json()   # CheckedClient fails the test on any ghs_ token
    assert got["state"] == "failed" and "***" in got["error"]
    assert "ghs_" not in str(world.db.tables["jobs"])


def test_desktop_pull_request_uses_the_users_own_token_and_the_fixes_branch(client, world, monkeypatch, tmp_path):
    from conftest import sign_in
    sign_in(client, ALICE)
    monkeypatch.setenv("DESKTOP_MODE", "1")
    world.gh.pats["ghp_alice_own"] = 101
    keys.set_many({"github": "ghp_alice_own"})
    ws = client.get("/api/workspaces").json()["active"]
    jid = world.db.add("jobs", {"ws": ws, "user_id": ALICE, "repo_url": "alice-gh/demo", "state": "ready",
                                "created": time.time(), "updated": time.time(), "fixes": [{"file": "a.py"}]})
    d = harness.data_root() / str(jid) / "repo"
    d.mkdir(parents=True)
    (d / "a.py").write_text("fixed = True\n")
    r = client.post(f"/api/harness/jobs/{jid}/pr")
    assert r.status_code == 200, r.text
    _, repo = world.gh.repo_by_name("alice-gh/demo")
    assert repo["branches"]["main"] == "root5001" and repo["pulls"][0]["head"] == "fixes"
    audit = world.db.tables["github_audit_log"]
    assert audit and all(a["via"] == "token" and a["installation_id"] is None and a["user_id"] == ALICE for a in audit)
    # someone else's repo through the same token: refused before any write
    jid2 = world.db.add("jobs", {"ws": ws, "user_id": ALICE, "repo_url": "bob-gh/secret", "state": "ready",
                                 "created": time.time(), "updated": time.time(), "fixes": [{"file": "a.py"}]})
    d2 = harness.data_root() / str(jid2) / "repo"
    d2.mkdir(parents=True)
    (d2 / "a.py").write_text("x\n")
    assert client.post(f"/api/harness/jobs/{jid2}/pr").status_code == 404
    _, bob_repo = world.gh.repo_by_name("bob-gh/secret")
    assert "fixes" not in bob_repo["branches"]


def test_signed_out_requests_never_reach_the_database_as_a_user(client, world):
    for method, path in [("GET", "/api/workspaces"), ("GET", "/api/graph"), ("GET", "/api/keys"),
                         ("POST", "/api/remediations"), ("GET", "/api/harness/jobs"), ("GET", "/api/prefs")]:
        assert client.request(method, path, json={}).status_code in (401, 422)
    assert not [r for r in world.db.requests if r[0] in ("user", "service")]


def test_demo_user_has_no_special_powers(client, world):
    """There is no shared demo account any more: 'demo' is just another GitHub user."""
    demo = client_as(DEMO)
    assert demo.post("/api/auth/demo").status_code in (404, 405)
    assert demo.get("/api/config").json().get("demo") is None
