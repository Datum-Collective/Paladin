import subprocess
import threading
import time

import pytest

from app import fixers, harness
from conftest import sign_in
from fakes import ALICE, OTHER

SERVER = '''import os
import hashlib
from flask import Flask, request
app = Flask(__name__)
API_KEY = "sk-live-abcdef1234567890"

@app.post("/h")
def h():
    return hashlib.md5(b"x").hexdigest()

if __name__ == "__main__":
    app.run(debug=True)
'''


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("APC_ALLOW_LOCAL", "1")
    r = tmp_path / "victim"
    r.mkdir()
    (r / "server.py").write_text(SERVER)
    (r / "README.md").write_text("hi")
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"], "HOME": str(tmp_path)}
    for cmd in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "init"]):
        subprocess.run(["git", *cmd], cwd=r, env=env, check=True)
    return r


def test_url_validation(monkeypatch):
    monkeypatch.delenv("APC_ALLOW_LOCAL", raising=False)
    assert harness.parse_url("https://github.com/octo/hello")[:2] == ("octo", "hello")
    assert harness.parse_url("https://github.com/octo/hello.git/")[:2] == ("octo", "hello")
    for bad in ("http://github.com/a/b", "https://evil.com/a/b", "https://github.com/a/b/../../c",
                "file:///etc/passwd", "git@github.com:a/b.git", "https://github.com.evil.com/a/b", "/etc"):
        with pytest.raises(ValueError):
            harness.parse_url(bad)


def test_deterministic_fixers():
    f = {"file": "a.py", "rule": "weak-hash", "line": 2, "cwe": "", "technique": ""}
    r = fixers.try_fix("import hashlib\nh = hashlib.md5(b'x')\n", f)
    assert r and "sha256" in r["content"] and r["method"] == "rule"
    f = {"file": "a.py", "rule": "hardcoded-secret", "line": 1, "cwe": "", "technique": ""}
    r = fixers.try_fix('TOKEN = "abcdefghijklmnop"\n', f)
    assert r and 'os.environ.get("TOKEN"' in r["content"] and r["content"].startswith("import os")


def test_unsafe_ai_patch_is_rejected(monkeypatch):
    f = {"file": "a.py", "rule": "code-exec", "line": 1, "cwe": "", "technique": ""}
    src = "x = eval(input())\n"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    # patch that breaks syntax, one that does not remove the finding, one whose old text is absent
    for bad in ('{"old":"x = eval(input())","new":"x = ((("}',
                '{"old":"x = eval(input())","new":"x = eval(input())  # ok"}',
                '{"old":"nonexistent","new":"y"}'):
        monkeypatch.setattr(fixers.ai, "complete", lambda *a, _b=bad, **k: _b)
        assert fixers.try_fix(src, f) is None
    monkeypatch.setattr(fixers.ai, "complete", lambda *a, **k: '{"old":"eval(input())","new":"int(input())","explanation":"x"}')
    assert fixers.try_fix(src, f)["content"] == "x = int(input())\n"


def _login(c):
    sign_in(c)


def _wait(c, jid):
    harness.wait(jid, 60)
    return c.get(f"/api/harness/jobs/{jid}").json()


def test_end_to_end_local_branch_and_pr(client, world, repo, monkeypatch):
    sign_in(client, ALICE)
    j = client.post("/api/harness/jobs", json={"repo_url": str(repo)}).json()
    job = _wait(client, j["id"])
    assert job["state"] == "ready", job["error"] or job["log"]
    rules = {x["rule"] for x in job["fixes"]}
    assert {"hardcoded-secret", "weak-hash", "debug-on"} <= rules
    assert "sha256" in job["diff"] and "debug=False" in job["diff"]
    assert "sk-live-abcdef1234567890" not in str(job["findings"])  # redacted in stored findings
    assert '+API_KEY = os.environ.get("API_KEY", "")' in job["diff"]
    # repo is on the branch, committed, and still compiles
    new = (harness.data_root() / str(job["id"]) / "repo" / "server.py").read_text()
    compile(new, "server.py", "exec")
    # findings reached the graph
    assert any(n.startswith("code:") for p in client.get("/api/paths").json()["paths"] for n in p["nodes"])
    # A PR goes through the GitHub App, and only for a repo in the user's own installation
    # local jobs store a path; pretend this one was cloned from GitHub
    world.db.rows("jobs", id=job["id"])[0]["repo_url"] = "alice-gh/demo"
    r = client.post(f"/api/harness/jobs/{job['id']}/pr")
    assert r.status_code == 409 and "github app" in r.json()["detail"].lower()
    world.db.add("github_installations", {"user_id": ALICE, "installation_id": 1001,
                                          "github_account_login": "alice-gh"})
    r = client.post(f"/api/harness/jobs/{job['id']}/pr")
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "pr_opened" and r.json()["pr_url"] == "https://github.com/alice-gh/demo/pull/1"
    _, gh_repo = world.gh.repo_by_name("alice-gh/demo")
    assert gh_repo["branches"]["main"] == "root5001", "the default branch never moves"
    assert gh_repo["commit_parents"][gh_repo["branches"]["fixes"]] == ["root5001"]      # fast-forward on fixes
    assert "sha256" in gh_repo["written_content"]["server.py"]
    [pr] = gh_repo["pulls"]
    assert pr["head"] == "fixes" and pr["base"] == "main"
    assert [(a["action"], a["detail"]["status"]) for a in world.db.tables["github_audit_log"]] == [
        ("create_branch", "attempted"), ("create_branch", "ok"), ("commit", "attempted"), ("commit", "ok"),
        ("open_pr", "attempted"), ("open_pr", "ok")]


def test_validation_isolation_and_busy(client, repo):
    assert client.post("/api/harness/jobs", json={"repo_url": "https://github.com/a/b"}).status_code == 401
    _login(client)
    assert client.post("/api/harness/jobs", json={"repo_url": "https://evil.com/a/b"}).status_code == 422
    j = client.post("/api/harness/jobs", json={"repo_url": str(repo)}).json()
    harness.wait(j["id"])
    client.post("/api/auth/logout")
    sign_in(client, OTHER)
    assert client.get(f"/api/harness/jobs/{j['id']}").status_code == 404
    assert client.get(f"/api/harness/jobs/{j['id']}/patch").status_code == 404


def test_cancel_during_clone_terminates_worker_and_keeps_workspace(client, repo, monkeypatch):
    _login(client)
    cloning = threading.Event()

    def blocked_clone(args, **kwargs):
        cloning.set()
        assert kwargs["cancel"].wait(3), "clone did not receive cancellation"
        raise harness.Cancelled()

    monkeypatch.setattr(harness, "_git", blocked_clone)
    job = client.post("/api/harness/jobs", json={"repo_url": str(repo)}).json()
    assert cloning.wait(2)

    stopped = client.post(f"/api/harness/jobs/{job['id']}/cancel")
    harness.wait(job["id"], 3)

    assert stopped.status_code == 200
    assert client.get(f"/api/harness/jobs/{job['id']}").json()["state"] == "cancelled"
    assert (harness.data_root() / str(job["id"])).is_dir()


def test_cancel_during_scan_stops_before_results_are_persisted(client, repo, monkeypatch):
    _login(client)
    scanning = threading.Event()

    def clone(args, **kwargs):
        import shutil
        shutil.copytree(repo, args[-1])
        return ""

    def blocked_scan(files, cancelled):
        scanning.set()
        while not cancelled():
            time.sleep(0.01)
        raise InterruptedError("scan cancelled")

    monkeypatch.setattr(harness, "_git", clone)
    monkeypatch.setattr(harness.codescan, "scan_full", blocked_scan)
    job = client.post("/api/harness/jobs", json={"repo_url": str(repo)}).json()
    assert scanning.wait(2)

    stopped = client.post(f"/api/harness/jobs/{job['id']}/cancel")
    harness.wait(job["id"], 3)

    current = client.get(f"/api/harness/jobs/{job['id']}").json()
    assert stopped.status_code == 200 and current["state"] == "cancelled"
    assert current["findings"] == [] and current["fixes"] == []


def test_cancel_finished_job_is_a_noop(client, repo):
    _login(client)
    job = client.post("/api/harness/jobs", json={"repo_url": str(repo)}).json()
    finished = _wait(client, job["id"])
    assert finished["state"] in ("done", "ready")

    response = client.post(f"/api/harness/jobs/{job['id']}/cancel")

    assert response.status_code == 200
    assert response.json()["state"] == finished["state"]


def test_html_rules_and_fixers():
    src = '<a href="x" target="_blank">x</a>\n<script src="http://cdn.example.com/a.js"></script>\n'
    fs = __import__("app.codescan", fromlist=["x"]).static_scan([{"path": "index.html", "content": src}])
    assert {f["rule"] for f in fs} == {"blank-noopener", "http-script-src"}
    out = src
    for f in sorted(fs, key=lambda f: -f["line"]):
        r = fixers.try_fix(out, f)
        assert r, f["rule"]
        out = r["content"]
    assert 'rel="noopener noreferrer"' in out and "https://cdn.example.com" in out


def test_clean_and_unscannable_repos_say_so(client, tmp_path, monkeypatch):
    import subprocess, os
    monkeypatch.setenv("APC_ALLOW_LOCAL", "1")
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": os.environ["PATH"], "HOME": str(tmp_path)}

    def mk(name, files):
        r = tmp_path / name
        r.mkdir()
        for k, v in files.items():
            (r / k).write_text(v)
        for cmd in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "i"]):
            subprocess.run(["git", *cmd], cwd=r, env=env, check=True)
        return r

    sign_in(client)
    cases = [(mk("docs_only", {"README.md": "hi"}), "nothing to scan"),
             (mk("clean", {"index.html": '<a target="_blank" rel="noopener" href="x">x</a>'}), "no issues found")]
    for repo_dir, expect in cases:
        j = client.post("/api/harness/jobs", json={"repo_url": str(repo_dir)}).json()
        harness.wait(j["id"])
        job = client.get(f"/api/harness/jobs/{j['id']}").json()
        assert job["state"] == "done" and any(expect in l["msg"] for l in job["log"]), job["log"]


def test_rules_catch_short_key_names_and_quoted_sql():
    from app import codescan
    src = ('KEY = "sk-live-abcdef1234567890"\n'
           'db.execute("SELECT * FROM users WHERE name = \'" + name + "\'")\n'
           'cur.execute(f"DELETE FROM t WHERE id={i}")\n')
    rules = [f["rule"] for f in codescan.static_scan([{"path": "a.py", "content": src}])]
    assert rules.count("hardcoded-secret") == 1 and rules.count("sql-concat") == 2


def test_ai_patch_that_leaves_user_input_in_executor_is_rejected(monkeypatch):
    f = {"file": "a.py", "rule": "shell-injection", "line": 3, "cwe": "", "technique": ""}
    src = "import subprocess\nfrom flask import request\nsubprocess.run(request.form['c'], shell=True)\n"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    bad = '{"old":"subprocess.run(request.form[\'c\'], shell=True)","new":"subprocess.run(shlex.split(request.form[\'c\']))"}'
    monkeypatch.setattr(fixers.ai, "complete", lambda *a, **k: bad)
    assert fixers.try_fix(src, f) is None
    monkeypatch.setattr(fixers.ai, "complete", lambda *a, **k: '{"cannot_fix": true, "reason": "whole cmd is user input"}')
    assert fixers.try_fix(src, f) is None


# ---- how git is run ----
SENSITIVE = {"SUPABASE_SERVICE_KEY": "svc", "SUPABASE_ANON_KEY": "anon", "SUPABASE_JWT_SECRET": "jwt",
             "GITHUB_TOKEN": "ghp_server", "GITHUB_APP_PRIVATE_KEY": "pem", "GITHUB_APP_CLIENT_SECRET": "cs",
             "ANTHROPIC_API_KEY": "sk-ant", "OPENAI_API_KEY": "sk-oai", "APC_DESKTOP_TOKEN": "desk"}


def test_git_env_has_what_windows_needs_and_no_secrets(monkeypatch):
    """Without SYSTEMROOT, Windows cannot start networking and every clone fails with 'Could not resolve host'."""
    import os
    for k, v in {"SYSTEMROOT": r"C:\Windows", "WINDIR": r"C:\Windows", "TEMP": r"C:\t", "TMP": r"C:\t",
                 "HTTPS_PROXY": "http://proxy.campus:3128", "NO_PROXY": "localhost", **SENSITIVE}.items():
        monkeypatch.setenv(k, v)
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(cmd=cmd, env=kw["env"])
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(harness.subprocess, "run", fake_run)
    harness._git(["ls-remote", "https://github.com/a/b.git"])
    env, cmd = seen["env"], seen["cmd"]
    for k in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HTTPS_PROXY", "NO_PROXY"):
        assert env[k] == os.environ[k], k
    assert not set(SENSITIVE) & set(env), "a server secret was passed to git"
    assert not any(v in str(env) for v in SENSITIVE.values())
    # hardening is unchanged: no system or user config, no prompts, no credential helper, no hooks or symlinks
    assert env["GIT_CONFIG_NOSYSTEM"] == "1" and env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_TERMINAL_PROMPT"] == "0" and env["GCM_INTERACTIVE"] == "never"
    for opt in ("core.hooksPath=/dev/null", "core.symlinks=false", "protocol.ext.allow=never", "credential.helper=",
                "protocol.file.allow=never"):
        assert opt in cmd


def test_clone_token_goes_only_into_a_github_header(monkeypatch):
    env = harness.git_env("ghs_scoped")
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    assert "ghs_scoped" not in str(env)          # base64 inside the header value, never a URL or a plain variable


@pytest.mark.parametrize("stderr,expect", [
    ("Cloning into 'data_dir\jobs\9\repo'...\nfatal: unable to access 'https://github.com/a/b.git/': "
     "Could not resolve host: github.com\n", "network or DNS"),
    ("Cloning into 'x'...\nfatal: unable to access 'https://github.com/a/b.git/': Failed to connect to github.com "
     "port 443 after 21000 ms: Timed out\n", "network or DNS"),
    ("Cloning into 'x'...\nremote: Repository not found.\nfatal: repository 'https://github.com/a/b.git/' not found\n",
     "not found"),
    ("Cloning into 'x'...\nfatal: could not read Username for 'https://github.com': terminal prompts disabled\n",
     "not found"),
    # a repo named like a network word, in a job folder named 403, is still classified by git's error line only
    ("Cloning into 'data_dir\jobs\403\ssl-timed-out'...\nfatal: weird\n", "server log"),
])
def test_git_errors_say_what_kind_of_failure_without_paths(monkeypatch, stderr, expect):
    monkeypatch.setattr(harness.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 128, "", stderr))
    with pytest.raises(RuntimeError) as e:
        harness._git(["clone", "https://github.com/a/b.git", "dest"], token="ghs_t")
    msg = str(e.value)
    assert expect in msg and "data_dir" not in msg and "jobs" not in msg and "ghs_t" not in msg


def test_scan_result_is_visible_to_the_live_stream_and_graph_api(client, world, repo):
    """Root cause of 'the graph never shows up': finishing a scan changed nothing the live stream watched."""
    sign_in(client, ALICE)
    before = client.get("/api/graph").json()
    assert before["nodes"] == []
    assert not world.db.tables.get("code_models")
    job = _wait(client, client.post("/api/harness/jobs", json={"repo_url": str(repo)}).json()["id"])
    assert job["state"] == "ready"
    [row] = world.db.tables["code_models"]
    assert row["created"] > 0       # `created` is what codescan.version() reports, and the stream watches it
    g = client.get("/api/graph").json()
    kinds = {n["kind"] for n in g["nodes"]}
    assert {"external", "component", "weakness", "data"} <= kinds
    w = next(n for n in g["nodes"] if n["kind"] == "weakness")
    assert w["meta"]["file"] == "server.py" and w["meta"]["line"] > 0
    assert {e["basis"] for e in g["edges"]} >= {"finding", "assumed"}
    p = client.get("/api/paths").json()["paths"][0]
    assert {h["basis"] for h in p["hops"]} >= {"finding", "assumed"}
