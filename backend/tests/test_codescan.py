import json

from app import codescan
from app.narrate import technique

VULN = '''
from flask import Flask, request
import hashlib, subprocess, sqlite3
app = Flask(__name__)
API_KEY = "sk-live-abcdef1234567890"

@app.post("/run")
def run():
    subprocess.run(request.form["cmd"], shell=True)
    db.execute("SELECT * FROM u WHERE n=" + request.args["n"])
    return hashlib.md5(b"x").hexdigest()
'''
FILES = [{"path": "app/server.py", "content": VULN},
         {"path": ".env", "content": "TOKEN=abcdefghijklmnop"},
         {"path": "../etc/passwd.py", "content": "x"},
         {"path": "node_modules/a/b.js", "content": "eval(x)"}]


def test_rule_techniques_exist_in_subset():
    for _, _, _, tech, *_ in codescan.RULES:
        assert technique(tech)["name"] != tech, f"{tech} missing from attack_subset.json"


def test_accept_files_filters():
    kept = codescan.accept_files(FILES)
    assert [f["path"] for f in kept] == ["app/server.py"]


def test_static_scan_finds_and_redacts():
    fs = codescan.static_scan(codescan.accept_files(FILES))
    rules = {f["rule"] for f in fs}
    assert {"hardcoded-secret", "shell-injection", "sql-concat", "weak-hash"} <= rules
    assert all("abcdef1234567890" not in f["snippet"] + f["context"] for f in fs)
    assert all(f["routed"] for f in fs)


def test_triage_validates_model_output(monkeypatch):
    fs = codescan.static_scan(codescan.accept_files(FILES))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    bad = json.dumps([{"id": "f1", "exploitable": False, "confidence": 5, "reason": "ok"},
                      {"id": "zzz", "exploitable": True}, {"id": "f2", "exploitable": "yes"}, "junk"])
    monkeypatch.setattr(codescan.ai, "complete", lambda *a, **k: "here: " + bad)
    assert codescan.triage(fs) is True
    assert fs[0]["exploitable"] is False and fs[0]["confidence"] == 1.0 and fs[0]["triaged_by"] == "haiku"
    assert fs[1]["exploitable"] is None  # non-bool answer ignored


def test_api_scan_builds_paths_and_isolated(client):
    client.post("/api/auth/demo")
    r = client.post("/api/codescan", json={"repo": "t", "files": FILES}).json()
    assert r["scanned"] and r["ai_used"] is False and len(r["findings"]) >= 4
    ps = client.get("/api/paths").json()
    assert any(n.startswith("code:") for p in ps["paths"] for n in p["nodes"])
    fx = client.get("/api/fixes").json()
    edges = fx["best_single"]["edges"]
    rid = client.post("/api/remediations", json={"edges": edges}).json()["id"]  # code edges are targetable
    assert client.post(f"/api/remediations/{rid}/approve").status_code == 200
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={"email": "o@b.co", "password": "longenough1"})
    assert client.get("/api/codescan").json()["scanned"] is False


def test_scan_requires_auth(client):
    assert client.post("/api/codescan", json={"files": []}).status_code == 401
