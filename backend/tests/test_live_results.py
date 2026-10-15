"""Results appear while a scan is still running: rule hits first, AI findings as each file's review lands."""
import json
import os
import subprocess
import threading
import time

import pytest

from app import codescan, crawler, fixers, keys
from conftest import sign_in
from fakes import ALICE
from test_crawler import FILES, BY, _claim
from test_harness import _wait


def test_emit_happens_before_the_review_and_ids_never_change(monkeypatch):
    keys.set_many({"anthropic": "k"})
    monkeypatch.setattr(crawler.time, "monotonic", lambda: time.time() * 1000)   # no throttling in this test
    monkeypatch.setattr(codescan.ai, "complete", lambda *a, **k: None)
    monkeypatch.setenv("APC_OSV", "0")
    stages = []

    def fake_call(system, user, max_tokens, cancelled=lambda: False):
        stages.append("ai-called")
        return (json.dumps([_claim()]) if json.loads(user)["TARGET"]["file"] == "app/db.py" else "[]"), ""

    monkeypatch.setattr(crawler.ai, "call", fake_call)
    seen = []

    def emit(fs, refs, stage):
        seen.append((stage, [(f["id"], f["file"], f["rule"]) for f in fs], list(stages)))

    final, *_ = crawler.analyze(FILES, emit=emit)
    keys.clear()
    first = seen[0]
    assert first[0] == "rules" and first[2] == [] and first[1], "rule hits are emitted before any AI request"
    assert any(s[0] == "review" and any(r.startswith("ai-") or r == "sql-concat" for _, _, r in s[1]) for s in seen[1:])
    last_ids = {(i, f, r) for i, f, r in seen[-1][1]}
    first_ids = {(i, f, r) for i, f, r in first[1]}
    assert first_ids <= last_ids, "a finding keeps its id from the first update to the last"
    assert [f["id"] for f in final] == [f"f{n}" for n in range(1, len(final) + 1)]


def test_graph_paths_and_fixes_fill_in_while_the_ai_review_is_still_running(client, world, tmp_path, monkeypatch):
    monkeypatch.setenv("APC_ALLOW_LOCAL", "1")
    monkeypatch.setenv("APC_OSV", "0")
    r = tmp_path / "shop"
    for f in FILES:
        (r / f["path"]).parent.mkdir(parents=True, exist_ok=True)
        (r / f["path"]).write_text(f["content"])
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": os.environ["PATH"], "HOME": str(tmp_path)}
    for cmd in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "i"]):
        subprocess.run(["git", *cmd], cwd=r, env=env, check=True)
    keys.set_many({"anthropic": "k"})
    hold, reached = threading.Event(), threading.Event()

    def slow_call(system, user, max_tokens, cancelled=lambda: False):
        reached.set()
        hold.wait(10)                     # the model is "thinking": the scan is not finished
        return "[]", ""

    monkeypatch.setattr(crawler.ai, "call", slow_call)
    monkeypatch.setattr(codescan.ai, "complete", lambda *a, **k: None)
    monkeypatch.setattr(fixers.ai, "complete", lambda *a, **k: None)
    sign_in(client, ALICE)
    job = client.post("/api/harness/jobs", json={"repo_url": str(r)}).json()
    assert reached.wait(10)
    try:
        mid = client.get(f"/api/harness/jobs/{job['id']}").json()
        assert mid["state"] == "scanning"
        assert any(f["rule"] == "sql-concat" for f in mid["findings"]), "the findings list fills in mid-scan"
        paths = client.get("/api/paths").json()["paths"]
        assert paths, "attack paths exist before the AI review has finished"
        assert client.get("/api/fixes").json()["cheapest_cut"], "fixes are computed from the results so far"
        assert any(n["kind"] == "weakness" for n in client.get("/api/graph").json()["nodes"])
        # proposing a fix mid-scan explains why it has to wait
        edges = client.get("/api/fixes").json()["cheapest_cut"]["edges"]
        r2 = client.post("/api/remediations", json={"edges": edges, "title": "x"})
        assert r2.status_code == 422 and "still running" in r2.json()["detail"]
    finally:
        hold.set()
        keys.clear()
    done = _wait(client, job["id"])
    assert done["state"] in ("ready", "done")
    after = client.post("/api/remediations", json={"edges": client.get("/api/fixes").json()["cheapest_cut"]["edges"],
                                                    "title": "x"})
    # these findings have no deterministic rewrite and the AI fixer is stubbed off, so "no automatic fix" is the
    # honest answer; what must no longer be said is that the scan is still running
    assert "still running" not in after.text


def test_a_new_scan_does_not_show_the_previous_results(client, world, tmp_path, monkeypatch):
    monkeypatch.setenv("APC_ALLOW_LOCAL", "1")
    monkeypatch.setenv("APC_OSV", "0")
    monkeypatch.setattr(codescan.ai, "complete", lambda *a, **k: None)
    monkeypatch.setattr(fixers.ai, "complete", lambda *a, **k: None)

    def make(name, text):
        d = tmp_path / name
        d.mkdir()
        (d / "a.py").write_text(text)
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
               "PATH": os.environ["PATH"], "HOME": str(tmp_path)}
        for cmd in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "i"]):
            subprocess.run(["git", *cmd], cwd=d, env=env, check=True)
        return d

    sign_in(client, ALICE)
    dirty = make("dirty", "import hashlib\nx = hashlib.md5(b'a')\n")
    clean = make("clean", "print('hello')\n")
    _wait(client, client.post("/api/harness/jobs", json={"repo_url": str(dirty)}).json()["id"])
    assert client.get("/api/paths").json()["paths"]
    _wait(client, client.post("/api/harness/jobs", json={"repo_url": str(clean)}).json()["id"])
    assert client.get("/api/paths").json()["paths"] == []
    assert client.get("/api/codescan").json()["findings"] == []
