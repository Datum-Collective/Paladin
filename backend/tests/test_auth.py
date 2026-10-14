"""GitHub sign-in through Supabase: PKCE login, cookie sessions and refresh, clock skew, logout, account switching,
and ingest API keys."""
import threading
import time
from urllib.parse import parse_qs, urlparse

import jwt

from conftest import client_as, make_client, sign_in, sign_out
from fakes import ALICE, BOB, JWT_SECRET, access_token

LOG = ("May 14 13:05:11 WEB-BO-01 sshd[912]: Accepted password for www-data from 185.199.110.42 port 51544 ssh2")


def test_login_redirects_to_github_with_pkce_and_account_picker(client):
    r = client.get("/api/auth/login", follow_redirects=False)
    loc = urlparse(r.headers["location"])
    q = parse_qs(loc.query)
    assert loc.netloc == "fake.supabase.co" and loc.path == "/auth/v1/authorize"
    assert q["provider"] == ["github"] and q["prompt"] == ["select_account"]
    assert q["code_challenge_method"] == ["s256"] and q["redirect_to"] == ["http://localhost:5173/api/auth/callback"]
    # Sign-in itself asks GitHub for nothing beyond identity: no scopes param is sent
    assert "scopes" not in q
    assert "httponly" in r.headers["set-cookie"].lower()


def test_full_login_me_and_logout(client, world):
    assert client.get("/api/me").status_code == 401
    sign_in(client, ALICE)
    me = client.get("/api/me").json()
    assert me["login"] == "alice-gh" and me["id"] == ALICE
    assert client.post("/api/auth/logout").status_code == 200
    assert world.db.logouts == ["local"]          # this session only: the desktop app stays signed in
    assert client.get("/api/me").status_code == 401


def test_session_cookies_are_httponly(client):
    client.get("/api/auth/login", follow_redirects=False)
    r = client.get(f"/api/auth/callback?code={ALICE}", follow_redirects=False)
    cookies = [h for h in r.headers.get_list("set-cookie") if h.startswith(("sb_access=", "sb_refresh="))]
    assert len(cookies) == 2 and all("httponly" in h.lower() and "samesite=lax" in h.lower() for h in cookies)


def test_callback_without_verifier_fails(client):
    r = client.get(f"/api/auth/callback?code={ALICE}", follow_redirects=False)
    assert r.headers["location"] == "/?login_error=1"
    assert client.get("/api/me").status_code == 401


def test_callback_with_provider_error_fails(client):
    client.get("/api/auth/login", follow_redirects=False)
    r = client.get("/api/auth/callback?error=access_denied&error_description=nope", follow_redirects=False)
    assert r.headers["location"] == "/?login_error=1"


def test_expiring_session_is_refreshed_on_any_route(client, world):
    sign_in(client, ALICE)
    client.cookies.set("sb_access", access_token(ALICE, exp_in=30))     # under the refresh margin
    r = client.get("/api/workspaces")
    assert r.status_code == 200 and len(world.db.refreshed) == 1
    set_cookies = r.headers.get_list("set-cookie")
    assert any(h.startswith("sb_access=") for h in set_cookies) and any(h.startswith("sb_refresh=") for h in set_cookies)


def test_refresh_also_reaches_streaming_responses(client, world, monkeypatch):
    """Routes that return their own Response (SSE, plain text) must still carry the rotated cookies."""
    from app import store, supa

    def end_stream(ws):   # the live stream runs until the browser leaves; end it after the first check
        raise supa.DataError(503, "stop")

    monkeypatch.setattr(store, "event_count", end_stream)
    sign_in(client, ALICE)
    expired = jwt.encode({"sub": ALICE, "aud": "authenticated", "exp": int(time.time()) - 600}, JWT_SECRET,
                         algorithm="HS256")
    client.cookies.set("sb_access", expired)
    with client.stream("GET", "/api/stream") as r:
        assert r.status_code == 200
        assert any(h.startswith("sb_refresh=") for h in r.headers.get_list("set-cookie"))


def test_concurrent_requests_never_reuse_a_refresh_token(client, world):
    """Supabase rotates refresh tokens and treats reuse as theft (it revokes the session). A burst of requests with
    the same expiring session must send each refresh token to Supabase at most once. (A request that already carries
    the NEW token from the first refresh may legitimately refresh again with it.)"""
    sign_in(client, ALICE)
    client.cookies.set("sb_access", access_token(ALICE, exp_in=5))
    statuses = []
    ts = [threading.Thread(target=lambda: statuses.append(client.get("/api/me").status_code)) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert statuses == [200] * 6
    assert world.db.refreshed and len(world.db.refreshed) == len(set(world.db.refreshed)), world.db.refreshed


def test_rejected_refresh_signs_out(client, world):
    sign_in(client, ALICE)
    world.db.fail_refresh = True
    client.cookies.set("sb_access", access_token(ALICE, exp_in=-600))
    r = client.get("/api/workspaces")
    assert r.status_code == 401
    assert any(h.startswith('sb_refresh=""') or "max-age=0" in h.lower() for h in r.headers.get_list("set-cookie"))


def test_token_issued_slightly_in_the_future_is_accepted(client):
    """This machine's clock may run a few seconds behind Supabase's."""
    client.cookies.set("sb_access", access_token(ALICE, iat_offset=5))
    assert client.get("/api/me").status_code == 200


def test_garbage_and_forged_tokens_are_401(client):
    client.cookies.set("sb_access", "garbage")
    assert client.get("/api/me").status_code == 401
    forged = jwt.encode({"sub": BOB, "aud": "authenticated", "exp": int(time.time()) + 600}, "not-the-secret",
                        algorithm="HS256")
    client.cookies.set("sb_access", forged)
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/workspaces").status_code == 401


def test_account_switching(client):
    sign_in(client, ALICE)
    assert client.get("/api/me").json()["login"] == "alice-gh"
    sign_out(client)
    sign_in(client, BOB)
    assert client.get("/api/me").json()["login"] == "bob-gh"


# ---- ingest API keys ----

def test_api_keys_are_per_user_and_revocable(client, world):
    alice = client_as(ALICE)
    raw = alice.post("/api/keys", json={"label": "syslog"}).json()["key"]
    assert raw.startswith("apc_")
    [row] = world.db.tables["api_keys"]
    assert row["key_hash"] != raw and raw not in str(row)               # only the hash is stored
    keys = alice.get("/api/keys").json()["keys"]
    assert [k["label"] for k in keys] == ["syslog"] and "key_hash" not in keys[0]
    bob = client_as(BOB)
    assert bob.get("/api/keys").json()["keys"] == []
    assert bob.delete(f"/api/keys/{keys[0]['id']}").status_code == 404   # not Bob's
    assert bob.delete("/api/keys/not-a-uuid").status_code == 404

    shipper = make_client()
    r = shipper.post("/api/ingest", headers={"X-API-Key": raw}, json={"format": "linux_auth", "lines": [LOG]})
    assert r.status_code == 200 and r.json()["accepted"] == 1
    assert alice.get("/api/graph").json()["events"] == 1
    assert bob.get("/api/graph").json()["events"] == 0

    assert alice.delete(f"/api/keys/{keys[0]['id']}").status_code == 200
    r = shipper.post("/api/ingest", headers={"X-API-Key": raw}, json={"format": "linux_auth", "lines": [LOG]})
    assert r.status_code == 401


def test_a_key_writes_only_into_its_own_workspace(client, world):
    alice = client_as(ALICE)
    first = alice.get("/api/workspaces").json()["active"]
    raw = alice.post("/api/keys", json={"label": "a"}).json()["key"]
    second = alice.post("/api/workspaces", json={"name": "Second"}).json()["workspace"]["id"]
    make_client().post("/api/ingest", headers={"X-API-Key": raw}, json={"format": "linux_auth", "lines": [LOG]})
    assert alice.get("/api/graph", headers={"X-Workspace": str(first)}).json()["events"] == 1
    assert alice.get("/api/graph", headers={"X-Workspace": str(second)}).json()["events"] == 0


def test_a_key_cannot_be_bound_to_someone_elses_workspace(client, world):
    alice = client_as(ALICE)
    alice_ws = alice.get("/api/workspaces").json()["active"]
    bob = client_as(BOB)
    raw = bob.post("/api/keys", headers={"X-Workspace": str(alice_ws)}, json={"label": "sneaky"}).json()["key"]
    make_client().post("/api/ingest", headers={"X-API-Key": raw}, json={"format": "linux_auth", "lines": [LOG]})
    assert alice.get("/api/graph").json()["events"] == 0
    assert all(k["ws"] != alice_ws for k in world.db.tables["api_keys"])


def test_bad_keys_are_401(client):
    for key in ("apc_nope", "nope", "apc_" + "x" * 300):
        r = client.post("/api/ingest", headers={"X-API-Key": key}, json={"format": "linux_auth", "lines": [LOG]})
        assert r.status_code == 401
