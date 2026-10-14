import os
import subprocess

from app import fixers, harness
from conftest import sign_in

SERVER = '''import hashlib
from flask import Flask
app = Flask(__name__)
API_KEY = "sk-live-abcdef1234567890abcd"

def fp(s):
    return hashlib.md5(s.encode()).hexdigest()

if __name__ == "__main__":
    app.run(debug=True)
'''


def _repo(tmp_path, files):
    r = tmp_path / "victim"
    r.mkdir()
    for p, c in files.items():
        (r / p).parent.mkdir(parents=True, exist_ok=True)
        (r / p).write_text(c)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": os.environ["PATH"], "HOME": str(tmp_path)}
    for cmd in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "i"]):
        subprocess.run(["git", *cmd], cwd=r, env=env, check=True)
    return r


def test_each_fix_reports_the_checks_it_passed():
    f = {"file": "a.py", "rule": "weak-hash", "line": 2, "cwe": "", "technique": ""}
    r = fixers.try_fix("import hashlib\nh = hashlib.md5(b'x')\n", f)
    names = {c["name"]: c["passed"] for c in r["checks"]}
    assert names["file still parses"] and names["rule no longer matches"] and names["no new findings introduced"]
    assert all(c["passed"] for c in r["checks"])


def test_non_python_files_say_they_were_not_syntax_checked():
    f = {"file": "a.html", "rule": "http-script-src", "line": 1, "cwe": "", "technique": ""}
    r = fixers.try_fix('<script src="http://x.com/a.js"></script>\n', f)
    syn = next(c for c in r["checks"] if c["name"].startswith("syntax"))
    assert syn["passed"] is None and "not syntax-checked" in syn["name"]      # honest: not verified


def test_job_runs_independent_final_verification(client, tmp_path, monkeypatch):
    monkeypatch.setenv("APC_ALLOW_LOCAL", "1")
    repo = _repo(tmp_path, {"server.py": SERVER})
    sign_in(client)
    j = client.post("/api/harness/jobs", json={"repo_url": str(repo)}).json()
    harness.wait(j["id"])
    job = client.get(f"/api/harness/jobs/{j['id']}").json()
    assert job["state"] == "ready", job["log"]
    v = job["report"]["verification"]
    assert v["python_files_compiled"] == v["python_files_changed"] == 1
    assert v["findings_before"] > v["findings_after"] and v["fixed_rules_still_matching"] == []
    # evidence on disk, independent of the harness code path
    on_disk = (harness.data_root() / str(j["id"]) / "repo" / "server.py").read_text()
    compile(on_disk, "server.py", "exec")
    assert "sk-live-abcdef" not in on_disk and "sha256" in on_disk and "debug=False" in on_disk
    # the original working copy is never modified
    assert "sk-live-abcdef1234567890abcd" in (repo / "server.py").read_text()


def test_patched_file_endpoint_returns_content_and_is_path_safe(client, tmp_path, monkeypatch):
    monkeypatch.setenv("APC_ALLOW_LOCAL", "1")
    repo = _repo(tmp_path, {"server.py": SERVER, "README.md": "hi"})
    sign_in(client)
    j = client.post("/api/harness/jobs", json={"repo_url": str(repo)}).json()
    harness.wait(j["id"])
    ok = client.get(f"/api/harness/jobs/{j['id']}/file", params={"path": "server.py"})
    assert ok.status_code == 200 and "sha256" in ok.json()["content"] and ok.json()["changed_lines"]
    for bad in ("../../etc/passwd", "/etc/passwd", "README.md", ".git/config", "nope.py"):
        assert client.get(f"/api/harness/jobs/{j['id']}/file", params={"path": bad}).status_code in (404, 422), bad


def test_old_job_directories_are_cleaned_up(client, tmp_path, monkeypatch):
    import time
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
    root = harness.data_root()
    old, fresh = root / "901", root / "902"
    for d in (old, fresh):
        (d / "repo").mkdir(parents=True)
    t = time.time() - 3 * 86400
    os.utime(old, (t, t))
    harness.cleanup_old(max_age_s=86400)
    assert not old.exists() and fresh.exists()
