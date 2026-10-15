import json

from app import codescan
from app.narrate import technique
from conftest import sign_in
from fakes import OTHER

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
    sign_in(client)
    r = client.post("/api/codescan", json={"repo": "t", "files": FILES}).json()
    assert r["scanned"] and r["ai_used"] is False and len(r["findings"]) >= 4
    ps = client.get("/api/paths").json()
    assert any(n.startswith("code:") for p in ps["paths"] for n in p["nodes"])
    fx = client.get("/api/fixes").json()
    edges = fx["best_single"]["edges"]
    rid = client.post("/api/remediations", json={"edges": edges}).json()["id"]  # code edges are targetable
    assert client.post(f"/api/remediations/{rid}/approve").status_code == 200
    client.post("/api/auth/logout")
    sign_in(client, OTHER)
    assert client.get("/api/codescan").json()["scanned"] is False


def test_scan_requires_auth(client):
    assert client.post("/api/codescan", json={"files": []}).status_code == 401


# ---- graph model: what each node is, and how each step is supported ----
def _finding(**kw):
    base = {"id": "f1", "file": "app/views.py", "line": 12, "rule": "sql-concat", "cwe": "CWE-89", "technique": "T1190",
            "sink": "db", "title": "SQL built from strings", "routed": True, "snippet": "cur.execute(f'...')",
            "exploitable": None, "confidence": 0.5, "reason": "", "triaged_by": "static"}
    return {**base, **kw}


def test_model_labels_kinds_and_basis_of_every_step():
    m = codescan.to_model([_finding(), _finding(id="f2", file="util.py", routed=False, sink="secret", rule="hardcoded-secret")],
                          lambda t: "M1")
    nodes = {n["id"]: n for n in m["nodes"]}
    assert nodes["code:internet"]["kind"] == "external"
    assert nodes["code:app/views.py"]["kind"] == "component" and nodes["code:app/views.py"]["meta"]["routed"] is True
    w = nodes["code:finding:f1"]
    assert w["kind"] == "weakness" and w["meta"]["file"] == "app/views.py" and w["meta"]["line"] == 12
    assert w["meta"]["cwe"] == "CWE-89" and w["meta"]["confirmed"] is False
    edges = {e["id"]: e for e in m["edges"]}
    assert edges["code:f1"]["basis"] == "finding" and "app/views.py:12" in edges["code:f1"]["note"]
    assert edges["code:sink:f1"]["basis"] == "assumed"                    # impact is inferred, never claimed as proof
    assert edges["code:in:app/views.py"]["basis"] == "assumed" and "route handler" in edges["code:in:app/views.py"]["note"]
    assert "unverified" in edges["code:in:util.py"]["note"]               # no route found: say so, low prior
    assert edges["code:in:util.py"]["p"] < edges["code:in:app/views.py"]["p"]


def test_triaged_exploitable_finding_is_marked_confirmed_and_not_exploitable_is_dropped():
    m = codescan.to_model([_finding(exploitable=True, confidence=0.9), _finding(id="f2", exploitable=False)], lambda t: "")
    ids = {n["id"] for n in m["nodes"]}
    assert "code:finding:f1" in ids and "code:finding:f2" not in ids
    assert next(n for n in m["nodes"] if n["id"] == "code:finding:f1")["meta"]["confirmed"] is True


def test_long_paths_and_reasons_never_push_a_note_past_the_edge_limit():
    """An over-long note would fail Edge validation and silently drop the whole path from the graph."""
    from app.models import Edge
    f = _finding(file="src/main/java/com/acme/web/controllers/" + "x" * 120 + "/AccountController.java", reason="r" * 200)
    m = codescan.to_model([f], lambda t: "")
    for e in m["edges"]:
        Edge(**e)
