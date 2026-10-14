"""Launcher support: workspace status, local folders (desktop), activity, storage, interrupted-job recovery."""
import json
import time
from pathlib import Path

import pytest

from app import harness, store

TOKEN = "t" * 40
LOG = ("May 14 13:05:11 WEB-BO-01 sshd[912]: Accepted password for www-data from 185.199.110.42 port 51544 ssh2")


def login(c):
    assert c.post("/api/auth/login", json={"email": "demo@example.com", "password": "demo-password"}).status_code == 200


@pytest.fixture()
def desktop(client, monkeypatch):
    monkeypatch.setenv("DESKTOP_MODE", "1")
    monkeypatch.setenv("APC_DESKTOP_TOKEN", TOKEN)
    login(client)
    return client


def git_repo(tmp_path: Path, name="proj") -> Path:
    d = tmp_path / name
    (d / ".git").mkdir(parents=True)
    return d


# ---- workspace listing carries source kind and scan status ----
def test_listing_reports_kind_and_status(client, monkeypatch):
    login(client)
    ws = client.post("/api/workspaces", json={"name": "Repo", "repo_url": "https://github.com/acme/api"}).json()["workspace"]
    assert ws["kind"] == "github" and ws["status"] is None
    harness._ensure()
    now = time.time()
    store.run("INSERT INTO jobs(ws,repo_url,state,error,created,updated) VALUES(?,?,?,?,?,?)",
              (ws["id"], "acme/api", "failed", "clone failed: repository not found", now, now))
    row = [w for w in client.get("/api/workspaces").json()["workspaces"] if w["id"] == ws["id"]][0]
    assert row["status"]["state"] == "failed" and "not found" in row["status"]["error"]
    empty = client.post("/api/workspaces", json={"name": "Blank"}).json()["workspace"]
    assert empty["kind"] == "empty"


# ---- local folders ----
def test_local_import_requires_desktop_mode(client, tmp_path):
    login(client)
    r = client.post("/api/workspaces/import-local", json={"path": str(git_repo(tmp_path))})
    assert r.status_code == 404


def test_local_resolve_and_import(desktop, tmp_path, monkeypatch):
    repo = git_repo(tmp_path, "my-service")
    started = {}
    monkeypatch.setattr(harness, "start", lambda ws, url: (started.update(ws=ws, url=url), {"id": 3, "state": "queued"})[1])
    pre = desktop.post("/api/repos/resolve-local", json={"path": str(repo)})
    assert pre.status_code == 200 and pre.json()["name"] == "my-service" and pre.json()["workspace_id"] is None
    r = desktop.post("/api/workspaces/import-local", json={"path": str(repo)})
    assert r.status_code == 200
    body = r.json()
    assert body["workspace"]["name"] == "my-service" and body["workspace"]["kind"] == "local"
    assert started == {"ws": body["workspace"]["id"], "url": str(repo.resolve())}
    again = desktop.post("/api/repos/resolve-local", json={"path": str(repo)}).json()
    assert again["workspace_id"] == body["workspace"]["id"]


@pytest.mark.parametrize("path,why", [("relative/dir", "absolute"), ("/definitely/not/here", "exist"), ("", "path")])
def test_local_import_rejects_bad_paths(desktop, path, why):
    r = desktop.post("/api/repos/resolve-local", json={"path": path})
    assert r.status_code == 422 and why in r.json()["detail"].lower()


def test_local_import_rejects_non_git_folders_with_guidance(desktop, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    r = desktop.post("/api/workspaces/import-local", json={"path": str(plain)})
    assert r.status_code == 422 and "git" in r.json()["detail"].lower()


def test_local_import_failure_leaves_no_workspace(desktop, tmp_path, monkeypatch):
    repo = git_repo(tmp_path)
    monkeypatch.setattr(harness, "start", lambda ws, url: (_ for _ in ()).throw(RuntimeError("a job is already running")))
    before = desktop.get("/api/workspaces").json()
    assert desktop.post("/api/workspaces/import-local", json={"path": str(repo)}).status_code == 409
    after = desktop.get("/api/workspaces").json()
    assert len(after["workspaces"]) == len(before["workspaces"])


# ---- activity ----
def test_activity_lists_scans_and_remediation_steps_newest_first(client):
    login(client)
    client.post("/api/ingest", json={"format": "linux_auth", "lines": [LOG]})
    fx = client.get("/api/fixes").json()
    client.post("/api/remediations", json={"edges": fx["cheapest_cut"]["edges"], "title": "Close the door"})
    harness._ensure()
    ws = client.get("/api/workspaces").json()["active"]
    now = time.time()
    store.run("INSERT INTO jobs(ws,repo_url,state,error,created,updated) VALUES(?,?,?,?,?,?)",
              (ws, "acme/api", "failed", "boom", now - 5, now - 5))
    items = client.get("/api/activity").json()["items"]
    kinds = {i["kind"] for i in items}
    assert kinds == {"scan", "remediation"}
    assert [i["ts"] for i in items] == sorted((i["ts"] for i in items), reverse=True)
    scan = [i for i in items if i["kind"] == "scan"][0]
    assert scan["state"] == "failed" and scan["detail"] == "boom" and scan["retry"] == "acme/api"
    rem = [i for i in items if i["kind"] == "remediation"][0]
    assert rem["title"] == "Close the door" and rem["action"] == "proposed"


def test_activity_is_scoped_to_the_workspace(client):
    login(client)
    harness._ensure()
    a = client.get("/api/workspaces").json()["active"]
    now = time.time()
    store.run("INSERT INTO jobs(ws,repo_url,state,created,updated) VALUES(?,?,?,?,?)", (a, "acme/api", "done", now, now))
    assert len(client.get("/api/activity").json()["items"]) == 1
    client.post("/api/workspaces", json={"name": "Other"})
    assert client.get("/api/activity").json()["items"] == []


# ---- storage ----
def test_storage_reports_sizes_and_clears_finished_clones(client, tmp_path):
    login(client)
    harness._ensure()
    ws = client.get("/api/workspaces").json()["active"]
    now = time.time()
    done = store.run("INSERT INTO jobs(ws,repo_url,state,created,updated) VALUES(?,?,?,?,?)", (ws, "a/b", "done", now, now))
    live = store.run("INSERT INTO jobs(ws,repo_url,state,created,updated) VALUES(?,?,?,?,?)", (ws, "a/c", "cloning", now, now))
    for jid in (done, live):
        d = harness.data_root() / str(jid) / "repo"
        d.mkdir(parents=True)
        (d / "f.txt").write_text("x" * 1000)
    s = client.get("/api/storage").json()
    assert s["clones"]["count"] == 2 and s["clones"]["bytes"] >= 2000 and s["database_bytes"] > 0
    pending = store.run("INSERT INTO jobs(ws,repo_url,state,created,updated) VALUES(?,?,?,?,?)", (ws, "a/d", "ready", now, now))
    (harness.data_root() / str(pending) / "repo").mkdir(parents=True)
    r = client.delete("/api/storage/clones").json()
    assert r["removed"] == 1
    assert (harness.data_root() / str(pending)).exists()          # fixes awaiting approval are kept
    assert not (harness.data_root() / str(done)).exists() and (harness.data_root() / str(live)).exists()


# ---- recovery ----
def test_interrupted_jobs_are_marked_failed_on_startup(client):
    harness._ensure()
    now = time.time()
    ids = [store.run("INSERT INTO jobs(ws,repo_url,state,created,updated) VALUES(?,?,?,?,?)", (1, "a/b", st, now, now))
           for st in ("queued", "cloning", "scanning", "fixing", "done", "failed")]
    n = harness.recover_interrupted()
    assert n == 4
    states = {r["id"]: (r["state"], r["error"]) for r in store.q("SELECT id,state,error FROM jobs")}
    for jid in ids[:4]:
        assert states[jid][0] == "failed" and "interrupted" in states[jid][1].lower()
    assert states[ids[4]][0] == "done"


# ---- new preferences ----
def test_new_preferences(client):
    login(client)
    p = client.get("/api/prefs").json()
    assert p["general.onboarding_dismissed"] is False and p["workspaces.sort"] == "recent"
    assert client.put("/api/prefs", json={"workspaces.sort": "name", "general.onboarding_dismissed": True}).status_code == 200
    assert client.put("/api/prefs", json={"workspaces.sort": "random"}).status_code == 422


def test_tilde_paths_are_expanded(desktop, tmp_path, monkeypatch):
    repo = git_repo(tmp_path, "home-proj")
    monkeypatch.setenv("HOME", str(tmp_path))
    r = desktop.post("/api/repos/resolve-local", json={"path": "~/home-proj"})
    assert r.status_code == 200 and r.json()["path"] == str(repo.resolve())


def test_pull_requests_are_refused_for_local_scans(client, monkeypatch):
    harness._ensure()
    now = time.time()
    jid = store.run("INSERT INTO jobs(ws,repo_url,state,created,updated) VALUES(?,?,?,?,?)",
                    (1, "/Users/me/proj", "ready", now, now))
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    with pytest.raises(RuntimeError, match="only available for GitHub"):
        harness.open_pr(1, jid)


def test_existing_workspace_is_not_switched_when_its_scan_cannot_start(desktop, tmp_path, monkeypatch):
    repo = git_repo(tmp_path)
    monkeypatch.setattr(harness, "start", lambda ws, url: {"id": 1, "state": "queued"})
    first = desktop.post("/api/workspaces/import-local", json={"path": str(repo)}).json()["workspace"]["id"]
    other = desktop.post("/api/workspaces", json={"name": "Other"}).json()["workspace"]["id"]
    monkeypatch.setattr(harness, "start", lambda ws, url: (_ for _ in ()).throw(RuntimeError("a job is already running")))
    assert desktop.post("/api/workspaces/import-local", json={"path": str(repo)}).status_code == 409
    assert desktop.get("/api/workspaces").json()["active"] == other and first != other


def test_a_real_local_repository_is_cloned_and_scanned_in_desktop_mode(desktop, tmp_path):
    """No mocks: git clones the folder, the scanner reads it, and the job settles (never stuck or failed)."""
    import shutil
    import subprocess
    if not shutil.which("git"):
        pytest.skip("git not installed")
    repo = tmp_path / "vuln-app"
    repo.mkdir()
    (repo / "app.py").write_text("import sqlite3\n\ndef find(uid):\n    c = sqlite3.connect('x')\n"
                                 "    return c.execute(\"SELECT * FROM users WHERE id = \" + uid).fetchall()\n")
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": __import__("os").environ["PATH"], "HOME": str(tmp_path)}
    for cmd in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "init"]):
        subprocess.run(["git", *cmd], cwd=repo, env=env, check=True)
    r = desktop.post("/api/workspaces/import-local", json={"path": str(repo)})
    assert r.status_code == 200, r.text
    jid = r.json()["job"]["id"]
    harness.wait(jid, timeout=60)
    ws = r.json()["workspace"]["id"]
    job = harness.get(ws, jid)
    assert job["state"] in ("done", "ready"), (job["state"], job["error"], job["log"][-3:])
    assert job["findings"], "the SQL injection in app.py should be found"
