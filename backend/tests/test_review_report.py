import json
import os
import subprocess

import pytest

from app import codescan, fixers, harness

CORS_PY = ('from fastapi import FastAPI\nfrom fastapi.middleware.cors import CORSMiddleware\napp = FastAPI()\n'
           'app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True)\n')


def test_permissive_cors_detected_and_fixed():
    fs = codescan.static_scan([{"path": "main.py", "content": CORS_PY}])
    assert [f["rule"] for f in fs] == ["permissive-cors"]
    r = fixers.try_fix(CORS_PY, fs[0])
    assert r and 'os.environ.get("ALLOWED_ORIGINS"' in r["content"] and "import os" in r["content"]
    compile(r["content"], "main.py", "exec")


SRC = "def get(id):\n    q = 'SELECT * FROM t WHERE id=' + id\n    return db.run(q)\n\nx = 1\n"


def test_ai_review_keeps_only_claims_that_match_the_file(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    claims = [
        {"file": "a.py", "line": 2, "quote": "q = 'SELECT * FROM t WHERE id=' + id", "category": "injection",
         "cwe": "CWE-89", "title": "SQL from string", "reason": "id is concatenated"},
        {"file": "a.py", "line": 2, "quote": "totally invented code", "category": "injection", "cwe": "CWE-89",
         "title": "x", "reason": "x"},                                   # quote not in file
        {"file": "a.py", "line": 99, "quote": "x = 1", "category": "other", "cwe": "CWE-20",
         "title": "x", "reason": "x"},                                   # line out of range
        {"file": "other.py", "line": 1, "quote": "def get(id):", "category": "other", "cwe": "CWE-20",
         "title": "x", "reason": "x"},                                   # unknown file
        {"file": "a.py", "line": 1, "quote": "def get(id):", "category": "other", "cwe": "<script>",
         "title": "x", "reason": "x"},                                   # bad cwe
    ]
    monkeypatch.setattr(codescan.ai, "complete", lambda *a, **k: "review:\n" + json.dumps(claims))
    out, stats = codescan.ai_review([{"path": "a.py", "content": SRC}], existing=[])
    assert [f["title"] for f in out] == ["SQL from string"]
    assert out[0]["rule"] == "ai-injection" and out[0]["technique"] == "T1190" and out[0]["triaged_by"] == "haiku-review"
    assert stats["files_reviewed"] == 1 and stats["claims_rejected"] == 4


def test_ai_review_skips_lines_static_rules_already_cover(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    claim = [{"file": "a.py", "line": 2, "quote": "q = 'SELECT", "category": "injection", "cwe": "CWE-89",
              "title": "dup", "reason": "x"}]
    monkeypatch.setattr(codescan.ai, "complete", lambda *a, **k: json.dumps(claim))
    out, _ = codescan.ai_review([{"path": "a.py", "content": SRC}], existing=[{"file": "a.py", "line": 2}])
    assert out == []


def test_fix_for_ai_review_finding_requires_parse_and_no_new_findings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    f = {"file": "a.py", "line": 2, "rule": "ai-injection", "cwe": "CWE-89", "technique": "T1190"}
    good = '{"old":"q = \'SELECT * FROM t WHERE id=\' + id\\n    return db.run(q)","new":"return db.run(\'SELECT * FROM t WHERE id=?\', (id,))","explanation":"param"}'
    monkeypatch.setattr(fixers.ai, "complete", lambda *a, **k: good)
    r = fixers.try_fix(SRC, f)
    assert r and "?" in r["content"] and r["method"] == "haiku"
    broken = '{"old":"x = 1","new":"x = ((("}'
    monkeypatch.setattr(fixers.ai, "complete", lambda *a, **k: broken)
    assert fixers.try_fix(SRC, f) is None


def _git_repo(tmp_path, files):
    r = tmp_path / "repo"
    r.mkdir()
    for p, c in files.items():
        (r / p).parent.mkdir(parents=True, exist_ok=True)
        (r / p).write_text(c)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": os.environ["PATH"], "HOME": str(tmp_path)}
    for cmd in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "i"]):
        subprocess.run(["git", *cmd], cwd=r, env=env, check=True)
    return r


def test_scan_report_explains_coverage_and_skips(client, tmp_path, monkeypatch):
    monkeypatch.setenv("APC_ALLOW_LOCAL", "1")
    repo = _git_repo(tmp_path, {
        "README.md": "docs", "notes.txt": "n", "logo.png": "binary",
        "node_modules/lib/index.js": "x=1", "dist/app.min.js": "x=1", "bundle.js.map": "{}",
        "app/main.py": CORS_PY, "app/util.py": "def f():\n    return 1\n",
    })
    client.post("/api/auth/demo")
    j = client.post("/api/harness/jobs", json={"repo_url": str(repo)}).json()
    harness.wait(j["id"])
    job = client.get(f"/api/harness/jobs/{j['id']}").json()
    rep = job["report"]
    assert rep["files_total"] == 8 and rep["scanned"] == 2 and rep["lines_scanned"] >= 6
    sk = rep["skipped"]
    assert sk["vendored or build output"]["count"] == 2          # node_modules + dist
    assert sk["docs"]["count"] == 2 and sk["binary or media"]["count"] == 1
    assert sk["lockfiles, minified, source maps"]["count"] == 1
    assert any(r["id"] == "permissive-cors" for r in rep["rules"])
    assert rep["candidates"] == 1 and rep["ai"]["enabled"] is False
    assert [f["rule"] for f in job["findings"]] == ["permissive-cors"]
    assert any("main.py" in x for x in rep["scanned_files"])


def test_zero_findings_still_reports_what_was_checked(client, tmp_path, monkeypatch):
    monkeypatch.setenv("APC_ALLOW_LOCAL", "1")
    repo = _git_repo(tmp_path, {"app/util.py": "def f():\n    return 1\n", "README.md": "x"})
    client.post("/api/auth/demo")
    j = client.post("/api/harness/jobs", json={"repo_url": str(repo)}).json()
    harness.wait(j["id"])
    job = client.get(f"/api/harness/jobs/{j['id']}").json()
    assert job["state"] == "done" and job["report"]["scanned"] == 1 and job["report"]["candidates"] == 0
    assert any("rules" in l["msg"] and "lines" in l["msg"] for l in job["log"]), job["log"]
