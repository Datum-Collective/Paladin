from urllib.parse import parse_qs, urlparse

import pytest

from app import github_access
from conftest import client_as
from fakes import ALICE, BOB, CAROL, now_iso


def start_install(c) -> str:
    r = c.get("/api/github/install-url")
    assert r.status_code == 200
    url = urlparse(r.json()["url"])
    assert url.netloc == "github.com" and url.path == "/apps/apc-test/installations/new"
    return parse_qs(url.query)["state"][0]


def callback(c, **params):
    return c.get("/api/github/callback", params=params, follow_redirects=False)


def connected(r) -> bool:
    assert r.status_code == 302
    return r.headers["location"] == "/?github_connected=1"


# --- install / link flow --------------------------------------------------------------------

def test_install_url_requires_login(world):
    assert client_as(None).get("/api/github/install-url").status_code == 401


def test_install_url_stores_only_state_hash(world):
    state = start_install(client_as(ALICE))
    [row] = world.db.tables["github_install_states"]
    assert row["user_id"] == ALICE and row["state_hash"] != state and state not in str(row)


def test_happy_path_links_installation_and_revokes_user_token(world):
    c = client_as(ALICE)
    state = start_install(c)
    r = callback(c, code=world.gh.code_for(101), installation_id="1001", setup_action="install", state=state)
    assert connected(r)
    assert world.db.tables["github_installations"] == [
        {"user_id": ALICE, "installation_id": 1001, "github_account_login": "alice-gh",
         "created_at": world.db.tables["github_installations"][0]["created_at"]}]
    assert len(world.gh.revoked) == 1 and world.gh.revoked[0].startswith("ghu_")  # token revoked, never stored
    assert "ghu_" not in str(world.db.tables)
    assert [i["installation_id"] for i in c.get("/api/github/installations").json()] == [1001]


def test_callback_requires_login(world):
    state = start_install(client_as(ALICE))
    r = callback(client_as(None), code=world.gh.code_for(101), installation_id="1001", state=state)
    assert not connected(r) and r.headers["location"] == "/?github_error=1"
    assert world.db.tables["github_installations"] == []


@pytest.mark.parametrize("state", [None, "", "made-up-state"])
def test_callback_rejects_bad_state(world, state):
    c = client_as(ALICE)
    start_install(c)
    params = {"code": world.gh.code_for(101), "installation_id": "1001"}
    if state is not None:
        params["state"] = state
    assert not connected(callback(c, **params))
    assert world.db.tables["github_installations"] == []


def test_callback_rejects_reused_state(world):
    c = client_as(ALICE)
    state = start_install(c)
    assert connected(callback(c, code=world.gh.code_for(101), installation_id="1001", state=state))
    world.db.tables["github_installations"].clear()
    assert not connected(callback(c, code=world.gh.code_for(101), installation_id="1001", state=state))
    assert world.db.tables["github_installations"] == []


def test_callback_rejects_expired_state(world):
    c = client_as(ALICE)
    state = start_install(c)
    world.db.tables["github_install_states"][0]["expires_at"] = now_iso(-1)
    assert not connected(callback(c, code=world.gh.code_for(101), installation_id="1001", state=state))
    assert world.db.tables["github_installations"] == []


def test_callback_rejects_another_users_state(world):
    bob_state = start_install(client_as(BOB))
    c = client_as(ALICE)
    assert not connected(callback(c, code=world.gh.code_for(101), installation_id="1001", state=bob_state))
    assert world.db.tables["github_installations"] == []
    # Bob's state is untouched and still works for Bob
    assert connected(callback(client_as(BOB), code=world.gh.code_for(102), installation_id="1002", state=bob_state))


def test_callback_rejects_installation_not_in_users_list(world):
    """Alice tampers with installation_id to claim Bob's installation."""
    c = client_as(ALICE)
    assert not connected(callback(c, code=world.gh.code_for(101), installation_id="1002", state=start_install(c)))
    assert not connected(callback(c, code=world.gh.code_for(101), installation_id="999999", state=start_install(c)))
    assert not connected(callback(c, code=world.gh.code_for(101), installation_id="1002 OR 1=1", state=start_install(c)))
    assert world.db.tables["github_installations"] == []


def test_callback_rejects_org_installation_visible_via_membership(world):
    c = client_as(ALICE)
    assert not connected(callback(c, code=world.gh.code_for(101), installation_id="1003", state=start_install(c)))
    assert world.db.tables["github_installations"] == []


def test_callback_rejects_code_from_a_different_github_account(world):
    """Signed in to our app as Alice, but github.com is signed in as Bob (or an attacker
    forces Bob's code onto Alice's browser). Bob's installation must not land on Alice."""
    c = client_as(ALICE)
    assert not connected(callback(c, code=world.gh.code_for(102), installation_id="1002", state=start_install(c)))
    # Bob can see Alice's installation as a collaborator; only the identity check stops this one
    assert not connected(callback(c, code=world.gh.code_for(102), installation_id="1001", state=start_install(c)))
    assert world.db.tables["github_installations"] == []


def test_callback_ignores_user_editable_metadata(world):
    """Supabase users can rewrite user_metadata.provider_id; the fake admin API returns
    999999 there. Linking still works because the app reads auth.identities instead."""
    c = client_as(ALICE)
    assert connected(callback(c, code=world.gh.code_for(101), installation_id="1001", state=start_install(c)))


def test_callback_rejects_blocked_account(world):
    c = client_as(CAROL)
    assert not connected(callback(c, code=world.gh.code_for(103), installation_id="1004", state=start_install(c)))
    assert world.db.tables["github_installations"] == []


def test_callback_rejects_bad_code(world):
    c = client_as(ALICE)
    assert not connected(callback(c, code="not-a-real-code", installation_id="1001", state=start_install(c)))
    assert world.db.tables["github_installations"] == []


def test_installation_cannot_be_linked_to_two_users(world):
    link(world, BOB, 1001)  # e.g. stale row; unique(installation_id) must hold
    c = client_as(ALICE)
    assert not connected(callback(c, code=world.gh.code_for(101), installation_id="1001", state=start_install(c)))
    assert [r["user_id"] for r in world.db.tables["github_installations"]] == [BOB]


# --- IDOR: Alice must not reach Bob's installation or repo in any way ----------------------

def link(world, uid, installation_id):
    world.db.add("github_installations", {
        "user_id": uid, "installation_id": installation_id,
        "github_account_login": world.gh.installations[installation_id]["account"]["login"]})


@pytest.fixture
def linked(world):
    link(world, ALICE, 1001)
    link(world, BOB, 1002)
    return world


def test_lists_only_own_installations_and_repos(linked):
    alice = client_as(ALICE)
    assert [i["installation_id"] for i in alice.get("/api/github/installations").json()] == [1001]
    repos = alice.get("/api/github/repos").json()
    assert [r["full_name"] for inst in repos for r in inst["repos"]] == ["alice-gh/demo"]
    bob = client_as(BOB)
    assert [r["full_name"] for inst in bob.get("/api/github/repos").json() for r in inst["repos"]] == ["bob-gh/secret"]


@pytest.mark.parametrize("method,url", [
    ("GET", "/api/github/manage-url/1002"),
    ("DELETE", "/api/github/installations/1002"),
    ("GET", "/api/github/manage-url/0"),
    ("GET", "/api/github/manage-url/abc"),
])
def test_other_users_installation_is_404(linked, method, url):
    r = client_as(ALICE).request(method, url)
    assert r.status_code == 404
    assert [(row["user_id"], row["installation_id"]) for row in linked.db.tables["github_installations"]] == [
        (ALICE, 1001), (BOB, 1002)]


FIX = {"title": "Fix", "commit_message": "fix", "files": [{"path": "README.md", "content": "pwned"}]}


@pytest.mark.parametrize("repo", ["bob-gh/secret", "BOB-GH/Secret", "bob-gh/SECRET", "acme/internal",
                                  "official-hackathon-org/app", "nobody/nothing"])
@pytest.mark.parametrize("method,suffix,kw", [
    ("GET", "tree", {}),
    ("GET", "file", {"params": {"path": "README.md"}}),
    ("POST", "fixes", {"json": FIX}),
])
def test_other_users_repo_is_404_on_every_endpoint(linked, repo, method, suffix, kw):
    r = client_as(ALICE).request(method, f"/api/github/repos/{repo}/{suffix}", **kw)
    assert r.status_code == 404
    assert not linked.gh.touched_repo(repo), "app called GitHub for a repo the user doesn't own"
    _, bob_repo = linked.gh.repo_by_name("bob-gh/secret")
    assert "fixes" not in bob_repo["branches"] and bob_repo["pulls"] == []


@pytest.mark.parametrize("owner,repo", [("..", "x"), ("alice-gh", ".."), ("alice-gh", "demo%2F..%2F..%2Fbob-gh"),
                                        ("-bad", "demo"), ("a" * 40, "demo"), ("alice-gh", "de mo")])
def test_malformed_owner_repo_is_404(linked, owner, repo):
    r = client_as(ALICE).get(f"/api/github/repos/{owner}/{repo}/tree")
    assert r.status_code == 404
    assert not any("/repos/" in p for _, p in linked.gh.calls)


def test_unauthenticated_requests_are_401(linked):
    anon = client_as(None)
    for method, url in [("GET", "/api/github/installations"), ("GET", "/api/github/repos"),
                        ("GET", "/api/github/manage-url/1001"), ("DELETE", "/api/github/installations/1001"),
                        ("GET", "/api/github/repos/alice-gh/demo/tree"),
                        ("POST", "/api/github/repos/alice-gh/demo/fixes")]:
        assert anon.request(method, url, json=FIX).status_code == 401, url


def test_installation_token_is_scoped_to_the_repo(linked):
    client_as(ALICE).get("/api/github/repos/alice-gh/demo/file", params={"path": "README.md"})
    scopes = {(inst, repo) for inst, repo, _ in linked.gh.inst_tokens.values()}
    assert (1001, 5001) in scopes and not any(inst == 1002 for inst, _ in scopes)


# --- reads -----------------------------------------------------------------------------------

def test_read_tree_and_file(linked):
    alice = client_as(ALICE)
    tree = alice.get("/api/github/repos/alice-gh/demo/tree").json()
    assert tree["ref"] == "main" and [e["path"] for e in tree["entries"]] == ["README.md"]
    f = alice.get("/api/github/repos/alice-gh/demo/file", params={"path": "README.md"}).json()
    assert f["content"] == "secret contents of alice-gh/demo" and f["binary"] is False


@pytest.mark.parametrize("path", ["../bob-gh/secret/README.md", "/etc/passwd", "a//b", "a\\b", "https://evil.example/x"])
def test_read_rejects_bad_paths(linked, path):
    r = client_as(ALICE).get("/api/github/repos/alice-gh/demo/file", params={"path": path})
    assert r.status_code == 422


@pytest.mark.parametrize("ref", ["..", "main..bob", "/main", "a b"])
def test_read_rejects_bad_refs(linked, ref):
    assert client_as(ALICE).get("/api/github/repos/alice-gh/demo/tree", params={"ref": ref}).status_code == 422


# --- writes ----------------------------------------------------------------------------------

def test_fix_creates_fixes_branch_commit_and_pr_then_reuses_pr(linked):
    alice = client_as(ALICE)
    _, repo = linked.gh.repo_by_name("alice-gh/demo")
    r = alice.post("/api/github/repos/alice-gh/demo/fixes", json=FIX)
    assert r.status_code == 201, r.text
    first = r.json()
    assert first["branch"] == "fixes" and first["pull_request"] == {
        "number": 1, "created": True, "html_url": "https://github.com/alice-gh/demo/pull/1"}
    assert repo["branches"]["main"] == "root5001", "default branch must never move"
    assert repo["branches"]["fixes"] == first["commit_sha"]

    second = alice.post("/api/github/repos/alice-gh/demo/fixes", json=FIX).json()
    assert second["pull_request"]["number"] == 1 and second["pull_request"]["created"] is False
    assert repo["commit_parents"][second["commit_sha"]] == [first["commit_sha"]]  # fast-forward
    assert repo["branches"]["main"] == "root5001" and len(repo["pulls"]) == 1

    actions = [(a["action"], a["detail"]["status"]) for a in linked.db.tables["github_audit_log"]]
    # append-only: every write is recorded as attempted BEFORE it is sent, then its result
    assert actions == [("create_branch", "attempted"), ("create_branch", "ok"), ("commit", "attempted"),
                       ("commit", "ok"), ("open_pr", "attempted"), ("open_pr", "ok"),
                       ("commit", "attempted"), ("commit", "ok")]
    assert all(a["user_id"] == ALICE and a["repo"] == "alice-gh/demo" and a["installation_id"] == 1001
               and a["via"] == "app" for a in linked.db.tables["github_audit_log"])


def test_fix_builds_on_commits_pushed_to_fixes_by_others(linked):
    alice = client_as(ALICE)
    _, repo = linked.gh.repo_by_name("alice-gh/demo")
    assert alice.post("/api/github/repos/alice-gh/demo/fixes", json=FIX).status_code == 201
    repo["branches"]["fixes"] = "human-commit"
    repo["commit_parents"]["human-commit"] = []
    sha = alice.post("/api/github/repos/alice-gh/demo/fixes", json=FIX).json()["commit_sha"]
    assert repo["commit_parents"][sha] == ["human-commit"]  # their work is kept, not overwritten


def test_fix_never_overwrites_a_concurrent_push(linked):
    alice = client_as(ALICE)
    _, repo = linked.gh.repo_by_name("alice-gh/demo")
    assert alice.post("/api/github/repos/alice-gh/demo/fixes", json=FIX).status_code == 201
    repo["push_during_commit"] = "racing-commit"
    assert alice.post("/api/github/repos/alice-gh/demo/fixes", json=FIX).status_code == 409
    assert repo["branches"]["fixes"] == "racing-commit"
    assert [a["detail"]["status"] for a in linked.db.tables["github_audit_log"]][-2:] == ["attempted", "failed"]


def test_fix_refuses_when_default_branch_is_fixes(linked):
    _, repo = linked.gh.repo_by_name("alice-gh/demo")
    repo["default_branch"] = "fixes"
    repo["branches"] = {"fixes": "root5001"}
    assert client_as(ALICE).post("/api/github/repos/alice-gh/demo/fixes", json=FIX).status_code == 409
    assert repo["branches"] == {"fixes": "root5001"}


@pytest.mark.parametrize("path", [".github/workflows/ci.yml", ".GITHUB/workflows/x.yml", ".git/config",
                                  "../escape", "a/../../b", ""])
def test_fix_rejects_forbidden_paths(linked, path):
    body = {**FIX, "files": [{"path": path, "content": "x"}]}
    assert client_as(ALICE).post("/api/github/repos/alice-gh/demo/fixes", json=body).status_code == 422
    assert linked.db.tables["github_audit_log"] == []


def test_fix_is_rate_limited_per_user(linked):
    alice = client_as(ALICE)
    codes = [alice.post("/api/github/repos/bob-gh/secret/fixes", json=FIX).status_code for _ in range(12)]
    assert codes[:10] == [404] * 10 and codes[10:] == [429, 429]
    # Bob's own limit is separate
    assert client_as(BOB).post("/api/github/repos/bob-gh/secret/fixes", json=FIX).status_code == 201


# --- unlink / account switching ----------------------------------------------------------------

def test_unlink_removes_only_own_link(linked):
    alice = client_as(ALICE)
    r = alice.delete("/api/github/installations/1001")
    assert r.status_code == 200 and r.json()["uninstall_url"] == "https://github.com/settings/installations/1001"
    assert [(row["user_id"], row["installation_id"]) for row in linked.db.tables["github_installations"]] == [(BOB, 1002)]
    assert alice.get("/api/github/repos").json() == []
    assert alice.get("/api/github/repos/alice-gh/demo/tree").status_code == 404


def test_switching_accounts_shows_only_that_accounts_data(linked):
    c = client_as(ALICE)
    assert [i["account"] for i in c.get("/api/github/installations").json()] == ["alice-gh"]
    assert c.post("/api/auth/logout").status_code == 200
    assert c.get("/api/github/installations").status_code == 401
    # Sign in as Bob through the real login flow on the same browser
    r = c.get("/api/auth/login", follow_redirects=False)
    assert parse_qs(urlparse(r.headers["location"]).query)["prompt"] == ["select_account"]
    assert c.get(f"/api/auth/callback?code={BOB}", follow_redirects=False).headers["location"] == "/"
    assert c.get("/api/me").json()["login"] == "bob-gh"
    assert [i["account"] for i in c.get("/api/github/installations").json()] == ["bob-gh"]
    assert c.get("/api/github/repos/alice-gh/demo/tree").status_code == 404


def test_disabled_without_config(linked, monkeypatch):
    monkeypatch.setattr(github_access.config, "GITHUB_ENABLED", False)
    assert client_as(ALICE).get("/api/github/installations").status_code == 503
