import subprocess
import time

import pytest

from app import fixers, harness

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
    c.post("/api/auth/demo")


def _wait(c, jid):
    harness.wait(jid, 60)
    return c.get(f"/api/harness/jobs/{jid}").json()


def test_end_to_end_local_branch_and_pr(client, repo, monkeypatch):
    _login(client)
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
    # PR needs a token, then goes through the GitHub API (mocked) once approved
    assert client.post(f"/api/harness/jobs/{job['id']}/pr").status_code == 409
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    calls = []

    def fake_api(method, path, token, body=None):
        calls.append((method, path))
        if path.endswith("/pulls"):
            assert body["head"] == job["branch"] and "Tests were not run" in body["body"]
            return {"html_url": "https://github.com/local/victim/pull/1"}
        return {"default_branch": "main", "permissions": {"push": True}}

    monkeypatch.setattr(harness, "gh_api", fake_api)
    monkeypatch.setattr(harness, "_git", lambda args, **k: "")
    monkeypatch.setattr(harness, "get", harness.get)
    # open_pr splits repo_url as owner/repo; local jobs store the path, so use a github-style name
    harness._upd(job["id"], repo_url="local/victim")
    r = client.post(f"/api/harness/jobs/{job['id']}/pr").json()
    assert r["state"] == "pr_opened" and r["pr_url"].endswith("/pull/1")
    assert ("POST", "/repos/local/victim/pulls") in calls


def test_validation_isolation_and_busy(client, repo):
    assert client.post("/api/harness/jobs", json={"repo_url": "https://github.com/a/b"}).status_code == 401
    _login(client)
    assert client.post("/api/harness/jobs", json={"repo_url": "https://evil.com/a/b"}).status_code == 422
    j = client.post("/api/harness/jobs", json={"repo_url": str(repo)}).json()
    harness.wait(j["id"])
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={"email": "o@b.co", "password": "longenough1"})
    assert client.get(f"/api/harness/jobs/{j['id']}").status_code == 404
    assert client.get(f"/api/harness/jobs/{j['id']}/patch").status_code == 404
