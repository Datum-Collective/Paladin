"""Repository crawler: deterministic index, import reachability, OSV advisories, Haiku review with validation."""
import json

import httpx
import pytest

from app import ai, codescan, crawler, keys

ROUTES_PY = '''from flask import Flask, request
from .db import find_user
from .auth import login_required

app = Flask(__name__)

@app.route("/users")
@login_required
def users():
    return find_user(request.args["name"])

@app.route("/health")
def health():
    return "ok"
'''
DB_PY = '''import sqlite3

def find_user(name):
    cur = sqlite3.connect("app.db").cursor()
    cur.execute(f"SELECT * FROM users WHERE name = '{name}'")
    return cur.fetchall()
'''
AUTH_PY = '''def login_required(fn):
    return fn
'''
SERVER_JS = '''const express = require('express')
const { run } = require('./lib/shell')
const app = express()
app.post('/run', (req, res) => res.send(run(req.body.cmd)))
'''
SHELL_JS = '''const { exec } = require('child_process')
exports.run = (cmd) => exec(cmd)
'''
FILES = [
    {"path": "app/routes.py", "content": ROUTES_PY}, {"path": "app/db.py", "content": DB_PY},
    {"path": "app/auth.py", "content": AUTH_PY}, {"path": "app/__init__.py", "content": ""},
    {"path": "web/server.js", "content": SERVER_JS}, {"path": "web/lib/shell.js", "content": SHELL_JS},
    {"path": "requirements.txt", "content": "flask==2.0.1\nrequests>=2\nPyYAML==5.3\n"},
    {"path": "web/package.json", "content": json.dumps({"dependencies": {"express": "4.17.1", "lodash": "^4.17.0"}})},
]
BY = {f["path"]: f["content"] for f in FILES}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    keys.clear()
    monkeypatch.setattr(ai, "BACKOFF", (0, 0, 0))
    monkeypatch.setenv("APC_OSV", "0")
    yield
    keys.clear()


def test_index_finds_entry_points_auth_sensitive_calls_imports_and_pinned_dependencies():
    idx = crawler.index(FILES)
    r = idx["files"]["app/routes.py"]
    assert [x["path"] for x in r["routes"]] == ["/users", "/health"]
    assert any("login_required" in a["text"] for a in r["auth"])
    assert {i["target"] for i in r["imports"]} == {"app/db.py", "app/auth.py"}
    assert {i["target"] for i in idx["files"]["web/server.js"]["imports"]} == {"web/lib/shell.js"}
    assert idx["files"]["web/server.js"]["routes"][0]["framework"] == "express"
    assert {s["kind"] for s in idx["files"]["app/db.py"]["sensitive"]} >= {"database"}
    deps = {(d["name"], d["version"]) for d in idx["dependencies"]}
    assert deps == {("flask", "2.0.1"), ("PyYAML", "5.3"), ("express", "4.17.1")}   # ranges are not guessed at
    assert set(idx["entries"]) == {"app/routes.py", "web/server.js"}


def test_reach_follows_imports_from_entry_points_with_line_evidence():
    chains = crawler.reach(crawler.index(FILES))
    assert chains["app/db.py"] == [{"file": "app/routes.py", "line": 2, "target": "app/db.py"}]
    assert chains["web/lib/shell.js"][0]["file"] == "web/server.js"
    assert "app/routes.py" not in chains


def _claim(**kw):
    base = {"file": "app/db.py", "line": 5, "quote": "cur.execute(f\"SELECT * FROM users WHERE name = '{name}'\")",
            "category": "injection", "cwe": "CWE-89", "severity": "critical", "status": "confirmed",
            "title": "SQL injection in find_user", "reason": "name comes from the query string", "impact": "read users",
            "evidence": [{"file": "app/routes.py", "line": 10, "quote": 'return find_user(request.args["name"])'}]}
    return {**base, **kw}


def test_validate_keeps_only_claims_that_quote_real_lines_and_downgrades_unproven_flows():
    good, rej = crawler.validate([_claim()], "app/db.py", BY, routed=False)
    assert rej == 0 and good[0]["status"] == "confirmed" and good[0]["exploitable"] is True
    assert good[0]["evidence"][0]["file"] == "app/routes.py" and good[0]["severity"] == "critical"
    bad = [_claim(line=4), _claim(quote="something that is not there"), _claim(file="app/routes.py"),
           _claim(cwe="SQLi"), "not a dict"]
    assert crawler.validate(bad, "app/db.py", BY, routed=False) == ([], 5)
    # a "confirmed" flow whose evidence does not match the code is only potential
    weak, _ = crawler.validate([_claim(evidence=[{"file": "app/routes.py", "line": 3, "quote": "nope"}])], "app/db.py", BY, False)
    assert weak[0]["status"] == "potential" and weak[0]["evidence"] == [] and weak[0]["exploitable"] is None


def test_review_sends_related_files_caches_and_keeps_partial_results(tmp_path, monkeypatch):
    keys.set_many({"anthropic": "k"})
    seen = []

    def fake_call(system, user, max_tokens, cancelled=lambda: False):
        body = json.loads(user)
        seen.append(body)
        if body["TARGET"]["file"] == "app/db.py":
            return json.dumps([_claim()]), ""
        if body["TARGET"]["file"] == "web/server.js":
            return None, "rate_limit"
        return "[]", ""

    monkeypatch.setattr(crawler.ai, "call", fake_call)
    idx = crawler.index(FILES)
    chains = crawler.reach(idx)
    out, stats = crawler.review(BY, idx, chains, [], cache_dir=tmp_path)
    db = next(b for b in seen if b["TARGET"]["file"] == "app/db.py")
    assert "--- app/routes.py" in db["RELATED"]                      # the caller is in the request
    assert db["FACTS"]["reached_from_entry_points_via_imports"][0]["file"] == "app/routes.py"
    assert [f["file"] for f in out] == ["app/db.py"] and stats["confirmed"] == 1   # no rule hit passed in: a new finding
    assert stats["failed"] == {"rate_limit": 1} and stats["partial"] is True
    n = len(seen)
    out2, stats2 = crawler.review(BY, idx, chains, [], cache_dir=tmp_path)
    assert stats2["cached"] >= 1 and out2[0]["title"] == out[0]["title"]
    assert len(seen) - n < n                                         # cached files were not sent again


def test_review_stops_early_when_the_key_is_rejected(monkeypatch):
    keys.set_many({"anthropic": "k"})
    calls = []
    monkeypatch.setattr(crawler, "CONCURRENCY", 1)
    monkeypatch.setattr(crawler.ai, "call", lambda *a, **k: (calls.append(1), (None, "auth"))[1])
    idx = crawler.index(FILES)
    out, stats = crawler.review(BY, idx, crawler.reach(idx), [])
    assert out == [] and stats["failed"]["auth"] >= 1 and len(calls) < len(crawler._priority(idx, crawler.reach(idx), [], BY))


def test_review_honours_cancellation(monkeypatch):
    keys.set_many({"anthropic": "k"})
    monkeypatch.setattr(crawler.ai, "call", lambda *a, **k: ("[]", ""))
    idx = crawler.index(FILES)
    with pytest.raises(InterruptedError):
        crawler.review(BY, idx, crawler.reach(idx), [], cancelled=lambda: True)


def test_advisories_report_published_ids_and_say_when_unavailable(monkeypatch):
    monkeypatch.setenv("APC_OSV", "1")
    deps = crawler.index(FILES)["dependencies"]

    def handler(req):
        qs = json.loads(req.content)["queries"]
        return httpx.Response(200, json={"results": [{"vulns": [{"id": "GHSA-xxxx"}]} if q["package"]["name"] == "PyYAML" else {} for q in qs]})

    real = httpx.post
    monkeypatch.setattr(crawler.httpx, "post", lambda url, **kw: httpx.Client(transport=httpx.MockTransport(handler)).post(url, **kw))
    out, note = crawler.advisories(deps)
    assert note == "" and len(out) == 1
    assert out[0]["file"] == "requirements.txt" and out[0]["line"] == 3 and out[0]["advisories"] == ["GHSA-xxxx"]
    assert "not checked" in out[0]["reason"]
    monkeypatch.setattr(crawler.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down")))
    assert crawler.advisories(deps) == ([], "dependency advisories unavailable (could not reach osv.dev)")
    monkeypatch.setattr(crawler.httpx, "post", real)


def test_analyze_end_to_end_builds_cross_file_attack_paths(monkeypatch):
    keys.set_many({"anthropic": "k"})

    def fake_call(system, user, max_tokens, cancelled=lambda: False):
        body = json.loads(user)
        return (json.dumps([_claim()]) if body["TARGET"]["file"] == "app/db.py" else "[]"), ""

    monkeypatch.setattr(crawler.ai, "call", fake_call)
    monkeypatch.setattr(codescan.ai, "complete", lambda *a, **k: None)        # triage off
    log = []
    findings, ai_used, n, stats, repo_map = crawler.analyze(FILES, progress=log.append)
    assert ai_used and n >= 5
    sql = [f for f in findings if f["file"] == "app/db.py" and f["line"] == 5]
    assert len(sql) == 1                                  # rule hit and review agree: one finding, not two
    assert sql[0]["status"] == "confirmed" and sql[0]["reviewed_by"] == "haiku-crawler"
    assert sql[0]["evidence"][0]["file"] == "app/routes.py" and sql[0]["severity"] == "critical"
    assert sql[0]["reached_via"][0]["file"] == "app/routes.py"
    assert any(f["file"] == "web/lib/shell.js" and f["rule"] in ("code-exec", "shell-injection") for f in findings)
    assert any(m.startswith("found 2 entry-point file(s)") for m in log)
    assert {e["file"] for e in repo_map["entries"]} == {"app/routes.py", "web/server.js"}
    model = codescan.to_model(findings, lambda t: "", repo_map["reach"])
    ref = [e for e in model["edges"] if e["basis"] == "reference"]
    assert any(e["src"] == "code:app/routes.py" and e["dst"] == "code:app/db.py" and "line 2" in e["note"] for e in ref)
    nodes = {nd["id"]: nd for nd in model["nodes"]}
    assert nodes["code:app/routes.py"]["meta"]["routed"] is True
    from app import analyze
    from app.models import Edge, Node
    g = analyze.build_graph([Node(**x) for x in model["nodes"]], [Edge(**x) for x in model["edges"]])
    paths = analyze.top_paths(g, 10)
    assert any(p["nodes"][:3] == ["code:internet", "code:app/routes.py", "code:app/db.py"] for p in paths)


def test_ai_call_retries_rate_limits_and_does_not_retry_auth(monkeypatch):
    keys.set_many({"anthropic": "k"})
    replies = [httpx.Response(429, headers={"retry-after": "0"}), httpx.Response(200, json={"content": [{"type": "text", "text": "[]"}]})]
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: replies.pop(0))
    assert ai.call("s", "u") == ("[]", "")
    n = []
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: (n.append(1), httpx.Response(401))[1])
    assert ai.call("s", "u") == (None, "auth") and len(n) == 1
    assert ai.call("s", "u", cancelled=lambda: True) == (None, "cancelled")


def test_related_excerpts_are_not_dropped_for_being_larger_than_the_budget():
    big = "\n".join(f"line_{i} = {i}  # padding to make this file long enough" for i in range(1, 400))
    text = crawler._excerpt("app/big.py", big, [200], 1500)
    assert "200|" in text and len(text) <= 1500 + len("--- app/big.py\n")


def test_unparseable_replies_are_failures_and_never_cached(tmp_path, monkeypatch):
    keys.set_many({"anthropic": "k"})
    monkeypatch.setattr(crawler.ai, "call", lambda *a, **k: ('Sure! [{"file": "app/db.py", "line": 5, "quote": ', ""))
    idx = crawler.index(FILES)
    out, stats = crawler.review(BY, idx, crawler.reach(idx), [], cache_dir=tmp_path)
    assert out == [] and stats["failed"].get("invalid", 0) >= 1 and stats["files_reviewed"] == 0
    assert not list(tmp_path.glob("*.json"))


def test_vendored_code_does_not_create_entry_points_but_manifests_still_count(monkeypatch):
    monkeypatch.setattr(crawler.ai, "call", lambda *a, **k: ("[]", ""))
    files = FILES + [{"path": "node_modules/express/example/app.js", "content": "app.get('/x', (q, r) => r.send(1))\n"}]
    _, _, _, _, repo_map = crawler.analyze(files)
    assert all("node_modules" not in e["file"] for e in repo_map["entries"])
    assert repo_map["dependencies"] == 3
