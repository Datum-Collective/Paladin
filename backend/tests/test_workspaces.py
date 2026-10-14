"""Workspaces as a first-class concept: isolation, switching, lifecycle, repo resolve/suggest/import, prefs."""
import json

import httpx
import pytest

from app import github, harness, keys, prefs
from conftest import sign_in
from fakes import DEMO, OTHER

LOG = ("May 14 13:05:11 WEB-BO-01 sshd[912]: Accepted password for www-data from 185.199.110.42 port 51544 ssh2")


def login(c):
    sign_in(c)


def gh(monkeypatch, handler):
    monkeypatch.setattr(github, "TRANSPORT", httpx.MockTransport(handler))


# ---- lifecycle and isolation ----
def test_every_user_has_a_default_workspace(client):
    login(client)
    r = client.get("/api/workspaces").json()
    assert len(r["workspaces"]) == 1 and r["active"] == r["workspaces"][0]["id"]
    assert r["workspaces"][0]["name"] == "Workspace"


def test_workspaces_isolate_data_and_switching_changes_what_endpoints_see(client):
    login(client)
    first = client.get("/api/workspaces").json()["active"]
    client.post("/api/ingest", json={"format": "linux_auth", "lines": [LOG]})
    assert client.get("/api/graph").json()["events"] == 1

    created = client.post("/api/workspaces", json={"name": "Second"}).json()
    assert created["workspace"]["id"] != first and created["active"] == created["workspace"]["id"]
    assert client.get("/api/graph").json()["events"] == 0          # new workspace is empty

    client.post(f"/api/workspaces/{first}/open")
    assert client.get("/api/graph").json()["events"] == 1          # first one kept its data


def test_active_workspace_persists_across_sessions(client):
    login(client)
    second = client.post("/api/workspaces", json={"name": "Second"}).json()["workspace"]["id"]
    client.post("/api/auth/logout")
    login(client)
    assert client.get("/api/workspaces").json()["active"] == second


def test_rename_validates_and_keeps_names_unique(client):
    login(client)
    a = client.get("/api/workspaces").json()["active"]
    b = client.post("/api/workspaces", json={"name": "Beta"}).json()["workspace"]["id"]
    assert client.patch(f"/api/workspaces/{b}", json={"name": "Alpha"}).status_code == 200
    assert client.patch(f"/api/workspaces/{a}", json={"name": "alpha"}).status_code == 409
    assert client.patch(f"/api/workspaces/{a}", json={"name": "  "}).status_code == 422
    assert client.patch(f"/api/workspaces/{a}", json={"name": "x" * 61}).status_code == 422


def test_delete_wipes_data_and_switches_away(client):
    login(client)
    first = client.get("/api/workspaces").json()["active"]
    second = client.post("/api/workspaces", json={"name": "Second"}).json()["workspace"]["id"]
    client.post("/api/ingest", json={"format": "linux_auth", "lines": [LOG]})
    r = client.delete(f"/api/workspaces/{second}")
    assert r.status_code == 200 and r.json()["active"] == first
    assert second not in [w["id"] for w in client.get("/api/workspaces").json()["workspaces"]]
    # recreating cannot resurrect old events
    again = client.post("/api/workspaces", json={"name": "Second"}).json()["workspace"]["id"]
    assert client.get("/api/graph").json()["events"] == 0
    assert again


def test_deleting_the_last_workspace_leaves_a_fresh_default(client):
    login(client)
    only = client.get("/api/workspaces").json()["active"]
    client.post("/api/ingest", json={"format": "linux_auth", "lines": [LOG]})
    r = client.delete(f"/api/workspaces/{only}").json()
    assert len(r["workspaces"]) == 1 and client.get("/api/graph").json()["events"] == 0


def test_users_cannot_touch_each_others_workspaces(client):
    login(client)
    mine = client.get("/api/workspaces").json()["active"]
    client.post("/api/auth/logout")
    sign_in(client, OTHER)
    for call in (lambda: client.post(f"/api/workspaces/{mine}/open"),
                 lambda: client.patch(f"/api/workspaces/{mine}", json={"name": "x"}),
                 lambda: client.delete(f"/api/workspaces/{mine}")):
        assert call().status_code == 404
    assert mine not in [w["id"] for w in client.get("/api/workspaces").json()["workspaces"]]


def test_workspace_count_is_capped(client):
    login(client)
    for i in range(49):
        assert client.post("/api/workspaces", json={"name": f"w{i}"}).status_code == 200
    assert client.post("/api/workspaces", json={"name": "one-too-many"}).status_code == 409


def test_api_key_ingests_into_the_workspace_it_was_created_in(client):
    login(client)
    first = client.get("/api/workspaces").json()["active"]
    key = client.post("/api/keys", json={"label": "ci"}).json()["key"]
    client.post("/api/workspaces", json={"name": "Elsewhere"})        # active workspace moves on
    client.post("/api/auth/logout")
    r = client.post("/api/ingest", headers={"X-API-Key": key}, json={"format": "linux_auth", "lines": [LOG]})
    assert r.status_code == 200 and r.json()["accepted"] == 1
    login(client)
    client.post(f"/api/workspaces/{first}/open")
    assert client.get("/api/graph").json()["events"] == 1


# ---- repo parsing / resolve / suggest / import ----
@pytest.mark.parametrize("text,expect", [
    ("https://github.com/acme/api", ("acme", "api")),
    ("https://github.com/acme/api.git", ("acme", "api")),
    ("https://github.com/acme/api/tree/main/src", ("acme", "api")),
    ("github.com/acme/api", ("acme", "api")),
    ("git@github.com:acme/api.git", ("acme", "api")),
    ("acme/api", ("acme", "api")),
    ("  acme/api  ", ("acme", "api")),
])
def test_github_parse_accepts_common_forms(text, expect):
    assert github.parse(text) == expect


@pytest.mark.parametrize("text", ["", "hello", "https://gitlab.com/a/b", "a/b/c", "http://github.com/a/b/../..", "../etc/passwd",
                                  "https://github.com/", "x" * 400, "src/main.py", "docs/readme.md", "github.com/torvalds",
                                  "a_b/c"])
def test_github_parse_rejects_other_input(text):
    assert github.parse(text) is None


def test_resolve_returns_repo_facts(client, monkeypatch):
    login(client)
    gh(monkeypatch, lambda r: httpx.Response(200, json={
        "full_name": "acme/api", "private": False, "default_branch": "main", "description": "API", "html_url": "https://github.com/acme/api"}))
    r = client.post("/api/repos/resolve", json={"query": "acme/api"})
    assert r.status_code == 200
    assert r.json() == {"owner": "acme", "repo": "api", "full_name": "acme/api", "private": False,
                        "default_branch": "main", "description": "API", "url": "https://github.com/acme/api",
                        "workspace_id": None}


def test_launcher_public_and_private_import_auth_flow(client, monkeypatch):
    """Regression for the real-account flow: public preview works anonymously; private import needs a token.
    A personal token is the desktop app's path (on the web, private repos come through the GitHub App, and a token
    is ignored: see test_isolation.py::test_server_github_token_is_never_used_on_the_web)."""
    login(client)
    monkeypatch.setenv("DESKTOP_MODE", "1")
    seen = []

    def handler(request):
        seen.append((request.url.path, request.headers.get("authorization")))
        name = request.url.path.rsplit("/", 1)[-1]
        if name == "private" and request.headers.get("authorization") != "Bearer ghp_test":
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(200, json={
            "full_name": f"acme/{name}", "private": name == "private", "default_branch": "main",
            "description": f"{name} fixture", "html_url": f"https://github.com/acme/{name}",
        })

    gh(monkeypatch, handler)
    public = client.post("/api/repos/resolve", json={"query": "acme/public"})
    assert public.status_code == 200 and public.json()["private"] is False

    hidden = client.post("/api/repos/resolve", json={"query": "acme/private"})
    assert hidden.status_code == 404 and "add a GitHub token" in hidden.json()["detail"]

    keys.set_many({"github": "ghp_test"})
    private = client.post("/api/repos/resolve", json={"query": "acme/private"})
    assert private.status_code == 200 and private.json()["private"] is True

    monkeypatch.setattr(harness, "start", lambda ws, url: {"id": 9, "state": "queued", "repo_url": "acme/private"})
    imported = client.post("/api/workspaces/import", json={"query": "acme/private"})
    assert imported.status_code == 200
    assert imported.json()["workspace"]["repo_url"] == "https://github.com/acme/private"
    assert seen == [
        ("/repos/acme/public", None),
        ("/repos/acme/private", None),
        ("/repos/acme/private", "Bearer ghp_test"),
        ("/repos/acme/private", "Bearer ghp_test"),
    ]


def test_resolve_errors_say_how_to_fix(client, monkeypatch):
    login(client)
    gh(monkeypatch, lambda r: httpx.Response(404, json={"message": "Not Found"}))
    r = client.post("/api/repos/resolve", json={"query": "acme/missing"})
    assert r.status_code == 404 and "github app" in r.json()["detail"].lower()   # web: private repos come via the App
    assert client.post("/api/repos/resolve", json={"query": "not a repo"}).status_code == 422
    gh(monkeypatch, lambda r: httpx.Response(403, headers={"x-ratelimit-remaining": "0"}, json={"message": "rate limit"}))
    assert client.post("/api/repos/resolve", json={"query": "acme/api"}).status_code == 429


def test_resolve_marks_an_existing_workspace(client, monkeypatch):
    login(client)
    gh(monkeypatch, lambda r: httpx.Response(200, json={"full_name": "acme/api", "private": False, "default_branch": "main",
                                                        "description": None, "html_url": "https://github.com/acme/api"}))
    monkeypatch.setattr(harness, "start", lambda ws, url: {"id": 1, "state": "queued", "repo_url": "acme/api"})
    made = client.post("/api/workspaces/import", json={"query": "acme/api"}).json()
    r = client.post("/api/repos/resolve", json={"query": "https://github.com/acme/api"}).json()
    assert r["workspace_id"] == made["workspace"]["id"]


def test_import_creates_activates_and_starts_a_scan(client, monkeypatch):
    login(client)
    gh(monkeypatch, lambda r: httpx.Response(200, json={"full_name": "acme/api", "private": False, "default_branch": "main",
                                                        "description": None, "html_url": "https://github.com/acme/api"}))
    started = {}

    def fake_start(ws, url):
        started.update(ws=ws, url=url)
        return {"id": 7, "state": "queued", "repo_url": "acme/api"}

    monkeypatch.setattr(harness, "start", fake_start)
    r = client.post("/api/workspaces/import", json={"query": "https://github.com/acme/api.git"})
    assert r.status_code == 200
    body = r.json()
    assert body["workspace"]["name"] == "acme/api" and body["workspace"]["repo_url"] == "https://github.com/acme/api"
    assert body["job"]["state"] == "queued" and body["active"] == body["workspace"]["id"]
    assert started == {"ws": body["workspace"]["id"], "url": "https://github.com/acme/api"}


def test_import_of_a_known_repo_reopens_instead_of_duplicating(client, monkeypatch):
    login(client)
    gh(monkeypatch, lambda r: httpx.Response(200, json={"full_name": "acme/api", "private": False, "default_branch": "main",
                                                        "description": None, "html_url": "https://github.com/acme/api"}))
    monkeypatch.setattr(harness, "start", lambda ws, url: {"id": 1, "state": "queued", "repo_url": "acme/api"})
    a = client.post("/api/workspaces/import", json={"query": "acme/api"}).json()
    client.post("/api/workspaces", json={"name": "Other"})
    b = client.post("/api/workspaces/import", json={"query": "acme/api"}).json()
    assert b["workspace"]["id"] == a["workspace"]["id"] and b["reopened"] is True
    assert len(client.get("/api/workspaces").json()["workspaces"]) == 3


def test_import_failure_does_not_leave_a_workspace_behind(client, monkeypatch):
    login(client)
    gh(monkeypatch, lambda r: httpx.Response(404, json={"message": "Not Found"}))
    before = len(client.get("/api/workspaces").json()["workspaces"])
    assert client.post("/api/workspaces/import", json={"query": "acme/missing"}).status_code == 404
    assert len(client.get("/api/workspaces").json()["workspaces"]) == before


def test_import_scan_start_failure_rolls_back_a_new_workspace(client, monkeypatch):
    login(client)
    gh(monkeypatch, lambda r: httpx.Response(200, json={"full_name": "acme/api", "private": False, "default_branch": "main",
                                                        "description": None, "html_url": "https://github.com/acme/api"}))

    def boom(ws, url):
        raise RuntimeError("a job is already running for this workspace")

    monkeypatch.setattr(harness, "start", boom)
    before = client.get("/api/workspaces").json()
    assert client.post("/api/workspaces/import", json={"query": "acme/api"}).status_code == 409
    after = client.get("/api/workspaces").json()
    assert len(after["workspaces"]) == len(before["workspaces"]) and after["active"] == before["active"]


def test_suggest_combines_workspaces_github_and_the_typed_url(client, monkeypatch):
    login(client)
    monkeypatch.setenv("DESKTOP_MODE", "1")      # a personal token is desktop-only
    keys.set_many({"github": "ghp_x"})
    client.post("/api/workspaces", json={"name": "payments-service", "repo_url": "https://github.com/acme/payments-service"})

    def handler(req):
        assert req.headers["authorization"] == "Bearer ghp_x"
        return httpx.Response(200, json=[
            {"full_name": "acme/payments", "private": True, "description": "pay", "html_url": "https://github.com/acme/payments", "pushed_at": "2026-10-01T00:00:00Z"},
            {"full_name": "acme/web", "private": False, "description": None, "html_url": "https://github.com/acme/web", "pushed_at": "2026-09-01T00:00:00Z"},
        ])

    gh(monkeypatch, handler)
    items = client.get("/api/repos/suggest", params={"q": "pay"}).json()["suggestions"]
    kinds = [i["kind"] for i in items]
    assert "workspace" in kinds and "github" in kinds
    assert all("pay" in (i["title"] + i.get("subtitle", "")).lower() for i in items)
    # a repo that already has a workspace is listed once, as the workspace
    gh(monkeypatch, lambda r: httpx.Response(200, json=[
        {"full_name": "acme/payments-service", "private": False, "description": None, "html_url": "https://github.com/acme/payments-service"}]))
    github.clear_cache()
    again = client.get("/api/repos/suggest", params={"q": "payments-service"}).json()["suggestions"]
    assert [i["kind"] for i in again] == ["workspace"]
    typed = client.get("/api/repos/suggest", params={"q": "someone/else"}).json()["suggestions"]
    assert typed[0]["kind"] == "url" and typed[0]["url"] == "https://github.com/someone/else"


def test_suggest_survives_github_being_unreachable(client, monkeypatch):
    login(client)
    monkeypatch.setenv("DESKTOP_MODE", "1")
    keys.set_many({"github": "ghp_x"})
    gh(monkeypatch, lambda r: (_ for _ in ()).throw(httpx.ConnectError("offline")))
    r = client.get("/api/repos/suggest", params={"q": ""})
    assert r.status_code == 200 and r.json()["github_error"]


def test_suggest_without_a_token_skips_github(client, monkeypatch):
    login(client)
    gh(monkeypatch, lambda r: pytest.fail("must not call GitHub without a token"))
    assert client.get("/api/repos/suggest", params={"q": "x"}).status_code == 200


def test_github_whoami(client, monkeypatch):
    login(client)
    monkeypatch.setenv("DESKTOP_MODE", "1")
    keys.set_many({"github": "ghp_x"})
    gh(monkeypatch, lambda r: httpx.Response(200, headers={"x-oauth-scopes": "repo, read:org"},
                                             json={"login": "octo", "name": "Octo"}))
    r = client.get("/api/github/status").json()
    assert r == {"mode": "token", "configured": True, "ok": True, "login": "octo", "scopes": ["repo", "read:org"]}
    gh(monkeypatch, lambda r: httpx.Response(401, json={"message": "Bad credentials"}))
    r = client.get("/api/github/status").json()
    assert r["configured"] is True and r["ok"] is False and "token" in r["error"].lower()


# ---- prefs ----
def test_prefs_defaults_validation_and_persistence(client):
    login(client)
    p = client.get("/api/prefs").json()
    assert p == prefs.DEFAULTS
    r = client.put("/api/prefs", json={"appearance.density": "compact", "diff.font_size": 14})
    assert r.status_code == 200 and r.json()["appearance.density"] == "compact"
    client.post("/api/auth/logout")
    login(client)
    assert client.get("/api/prefs").json()["diff.font_size"] == 14


@pytest.mark.parametrize("patch", [{"nope": 1}, {"appearance.density": "huge"}, {"general.startup": []}, {"appearance.density": {}},
                                   {"diff.font_size": 99},
                                   {"diff.wrap": "yes"}, {"general.startup": None}, {"assistant.model": "x" * 200}])
def test_prefs_reject_bad_input_and_apply_nothing(client, patch):
    login(client)
    r = client.put("/api/prefs", json={**patch, "appearance.graph_labels": False})
    assert r.status_code == 422
    assert client.get("/api/prefs").json()["appearance.graph_labels"] is True   # atomic: the valid half was not applied


def test_prefs_require_auth_and_are_per_user(client):
    assert client.get("/api/prefs").status_code == 401
    login(client)
    client.put("/api/prefs", json={"appearance.density": "compact"})
    client.post("/api/auth/logout")
    sign_in(client, OTHER)
    assert client.get("/api/prefs").json()["appearance.density"] == "comfortable"


def test_rate_limit_is_per_account_not_per_workspace(client, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "INGEST_RATE", (2, 60))
    main._hits.clear()
    login(client)
    body = {"format": "linux_auth", "lines": [LOG]}
    assert client.post("/api/ingest", json=body).status_code == 200
    assert client.post("/api/ingest", json=body).status_code == 200
    client.post("/api/workspaces", json={"name": "Fresh"})          # a new workspace must not reset the budget
    assert client.post("/api/ingest", json=body).status_code == 429


def test_request_can_pin_its_workspace_so_other_windows_cannot_redirect_it(client):
    login(client)
    a = client.get("/api/workspaces").json()["active"]
    b = client.post("/api/workspaces", json={"name": "B"}).json()["workspace"]["id"]      # active is now B
    r = client.post("/api/ingest", headers={"X-Workspace": str(a)}, json={"format": "linux_auth", "lines": [LOG]})
    assert r.status_code == 200
    assert client.get("/api/graph", headers={"X-Workspace": str(a)}).json()["events"] == 1
    assert client.get("/api/graph", headers={"X-Workspace": str(b)}).json()["events"] == 0
    assert client.get("/api/graph", params={"ws": a}).json()["events"] == 1                # query form (streams)
    assert client.get("/api/graph", headers={"X-Workspace": "999999"}).json()["events"] == 0   # not owned: ignored


def test_reimport_after_a_failed_scan_starts_a_new_one(client, monkeypatch):
    login(client)
    gh(monkeypatch, lambda r: httpx.Response(200, json={"full_name": "acme/api", "private": False, "default_branch": "main",
                                                        "description": None, "html_url": "https://github.com/acme/api"}))
    calls = []
    monkeypatch.setattr(harness, "start", lambda ws, url: (calls.append(url), {"id": len(calls), "state": "queued"})[1])
    a = client.post("/api/workspaces/import", json={"query": "acme/api"}).json()
    monkeypatch.setattr(harness, "list_jobs", lambda ws: [{"id": 1, "state": "failed"}])
    client.post("/api/workspaces/import", json={"query": "acme/api"})
    assert len(calls) == 2 and a["reopened"] is False
    monkeypatch.setattr(harness, "list_jobs", lambda ws: [{"id": 2, "state": "ready"}])
    monkeypatch.setattr(harness, "get", lambda ws, jid: {"id": jid, "state": "ready"})
    client.post("/api/workspaces/import", json={"query": "acme/api"})
    assert len(calls) == 2                                           # a finished scan is reused, not repeated


def test_concurrent_first_requests_create_exactly_one_default_workspace(client, world):
    import threading
    from app import supa, workspaces
    from fakes import access_token
    login(client)
    world.db.tables["workspaces"].clear()
    ids, errs = [], []

    def go():
        try:
            supa.set_user(access_token(DEMO), DEMO)
            ids.append(workspaces.ensure_default(DEMO))
        except Exception as e:  # pragma: no cover
            errs.append(e)

    ts = [threading.Thread(target=go) for _ in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs and len(set(ids)) == 1
    assert len(world.db.rows("workspaces", user_id=DEMO)) == 1
