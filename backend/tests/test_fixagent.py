"""The fixing agent. A scripted Claude speaks the real Messages streaming wire format through the official SDK (mock
transport); the repository's tests really run (pytest in a subprocess); the verdict never comes from the model."""
import json
import shlex
import subprocess
import sys
import threading

import anthropic
import httpx2
import pytest

from app import codescan, fixagent, mitre

APP = 'def calc(expr):\n    return eval(expr)\n'
TEST = 'import app\n\n\ndef test_calc_numbers():\n    assert app.calc("2") == 2\n'
OLD = "def calc(expr):\n    return eval(expr)\n"
GOOD = "import ast\n\n\ndef calc(expr):\n    return ast.literal_eval(expr)\n"


# ---- a scripted Claude behind the real SDK ---------------------------------------------------------------------------
def sse(events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def turn(calls, text="", stop=None):
    """One assistant turn as the API streams it: optional text, then tool_use blocks."""
    ev = [{"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant", "model": "m",
                                                "content": [], "stop_reason": None, "stop_sequence": None,
                                                "usage": {"input_tokens": 10, "output_tokens": 0}}}]
    i = 0
    if text:
        ev += [{"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
               {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
               {"type": "content_block_stop", "index": 0}]
        i = 1
    for n, (name, args) in enumerate(calls):
        ev += [{"type": "content_block_start", "index": i,
                "content_block": {"type": "tool_use", "id": f"toolu_{i}_{n}", "name": name, "input": {}}},
               {"type": "content_block_delta", "index": i,
                "delta": {"type": "input_json_delta", "partial_json": json.dumps(args)}},
               {"type": "content_block_stop", "index": i}]
        i += 1
    ev += [{"type": "message_delta", "delta": {"stop_reason": stop or ("tool_use" if calls else "end_turn"),
                                               "stop_sequence": None}, "usage": {"output_tokens": 5}},
           {"type": "message_stop"}]
    return sse(ev)


class Claude:
    def __init__(self, *turns, status=200):
        self.turns, self.bodies, self.status = list(turns), [], status

    def handler(self, req):
        body = json.loads(req.content)
        self.bodies.append({"path": req.url.path, "query": str(req.url.query), "headers": dict(req.headers), **body})
        if self.status != 200:
            return httpx2.Response(self.status, json={"type": "error", "error": {"type": "x", "message": "nope"}})
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=self.turns.pop(0))

    def install(self, monkeypatch):
        monkeypatch.setattr(fixagent, "CLIENT_FACTORY", lambda: anthropic.Anthropic(
            api_key="sk-ant-test", max_retries=0,
            http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(self.handler))))
        return self


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    (tmp_path / "app.py").write_text(APP)
    (tmp_path / "test_app.py").write_text(TEST)
    monkeypatch.setenv("APC_ALLOW_LOCAL_TESTS", "1")
    monkeypatch.setenv("APC_OSV", "0")
    monkeypatch.setattr(fixagent, "docker_ready", lambda: False)
    monkeypatch.setattr(fixagent, "detect_tests",
                        lambda root: f"{shlex.quote(sys.executable)} -m pytest -x -q -p no:cacheprovider")
    return tmp_path


def target(root):
    f = codescan.static_scan([{"path": "app.py", "content": (root / "app.py").read_text()}])[0]
    assert f["rule"] == "code-exec" and f["cwe"] == "CWE-95"
    return {**f, "id": "f1"}


def edit(new=GOOD, old=OLD, path="app.py"):
    return ("edit_file", {"path": path, "old": old, "new": new})


def finish(cites=("CWE-95", "CAPEC-35")):
    return ("finish", {"summary": "Replaced eval with ast.literal_eval.", "citations": list(cites)})


# ---- verdicts come from evidence ---------------------------------------------------------------------------------------
def test_a_real_fix_is_verified_by_rescan_real_tests_and_valid_citations(repo, monkeypatch):
    c = Claude(turn([("read_file", {"path": "app.py"}), ("mitre_lookup", {"id": "CWE-95"})], text="Looking."),
               turn([edit()]), turn([("rescan_file", {"path": "app.py"}), ("run_tests", {})]),
               turn([finish()])).install(monkeypatch)
    events = []
    r = fixagent.fix(repo, [target(repo)], emit=events.append)
    assert r["verdict"] == "verified", r["reason"]
    assert r["tests"]["after"]["ran"] and r["tests"]["after"]["passed"] and r["tests"]["after"]["runner"] == "this machine"
    assert r["resolved"][0]["how"] == "scanner no longer reports it" and not r["regressions"]
    assert r["grounding"] == {"citations": ["CWE-95", "CAPEC-35"], "fabricated": [], "unrelated": [], "ok": True,
                              "related_checked": True}
    assert "literal_eval" in r["diff"] and "literal_eval" in (repo / "app.py").read_text()
    kinds = [e["type"] for e in events]
    assert "text" in kinds and kinds.count("tool") == 6 and kinds.count("tool_result") == 6
    first = c.bodies[0]
    assert first["model"] == "claude-opus-5-5" and first["output_config"] == {"effort": "high"}
    assert first["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in first["headers"]["anthropic-beta"]
    assert "tool_choice" not in first and "temperature" not in first and "thinking" not in first
    assert {t["name"] for t in first["tools"]} == {"list_files", "read_file", "search_code", "edit_file",
                                                   "mitre_lookup", "run_tests", "rescan_file", "finish"}
    assert next(t for t in first["tools"] if t["name"] == "edit_file")["eager_input_streaming"] is True
    assert "CWE-95" in first["messages"][0]["content"] and "Eval Injection" in first["messages"][0]["content"]
    second = c.bodies[1]["messages"]
    assert second[-2]["role"] == "assistant" and second[-1]["role"] == "user"
    results = second[-1]["content"]
    assert [x["tool_use_id"] for x in results] == ["toolu_1_0", "toolu_2_1"] and not results[0]["is_error"]


def test_a_claimed_fix_without_a_change_is_not_a_fix(repo, monkeypatch):
    Claude(turn([("finish", {"summary": "Fixed and verified, all tests pass!", "citations": ["CWE-95"]})])) \
        .install(monkeypatch)
    r = fixagent.fix(repo, [target(repo)])
    assert r["verdict"] == "no_changes" and "Fixed and verified" in r["agent_claim"]


def test_a_cosmetic_edit_that_keeps_the_weakness_is_not_fixed(repo, monkeypatch):
    Claude(turn([edit(new="def calc(expr):\n    return eval(expr)  # safe\n")]), turn([finish()])).install(monkeypatch)
    r = fixagent.fix(repo, [target(repo)])
    assert r["verdict"] == "not_fixed" and r["unresolved"][0]["how"] == "scanner still reports it"


def test_a_fix_that_breaks_the_tests_is_rejected(repo, monkeypatch):
    Claude(turn([edit(new="def calc(expr):\n    return 0\n")]), turn([finish()])).install(monkeypatch)
    r = fixagent.fix(repo, [target(repo)])
    assert r["verdict"] == "failed_tests" and r["tests"]["after"]["passed"] is False


def test_made_up_or_missing_mitre_citations_withhold_verified(repo, monkeypatch):
    Claude(turn([edit()]), turn([finish(("CWE-95", "CWE-99999"))])).install(monkeypatch)
    r = fixagent.fix(repo, [target(repo)])
    assert r["verdict"] == "ungrounded" and r["grounding"]["fabricated"] == ["CWE-99999"]
    (repo / "app.py").write_text(APP)
    Claude(turn([edit()]), turn([finish(())])).install(monkeypatch)
    r = fixagent.fix(repo, [target(repo)])
    assert r["verdict"] == "ungrounded" and "cited no MITRE" in r["reason"]


def test_unrelated_citations_are_flagged(repo, monkeypatch):
    Claude(turn([edit()]), turn([finish(("CWE-95", "T1566"))])).install(monkeypatch)   # phishing: real but unrelated
    r = fixagent.fix(repo, [target(repo)])
    assert r["verdict"] == "verified" and r["grounding"]["unrelated"] == ["T1566"]


def test_without_a_sandbox_a_good_fix_is_never_called_verified(repo, monkeypatch):
    monkeypatch.delenv("APC_ALLOW_LOCAL_TESTS")
    Claude(turn([edit()]), turn([finish()])).install(monkeypatch)
    r = fixagent.fix(repo, [target(repo)])
    assert r["verdict"] == "fixed_untested" and "Docker sandbox is not available" in r["reason"]


def test_the_agent_cannot_weaken_checks_or_leave_the_repository(repo, monkeypatch):
    (repo.parent / "outside.txt").write_text("secret")
    (repo / "link").symlink_to(repo.parent)
    calls = [("edit_file", {"path": "test_app.py", "old": "assert", "new": "pass  #"}),
             ("read_file", {"path": "../outside.txt"}), ("read_file", {"path": "/etc/passwd"}),
             ("read_file", {"path": "link/outside.txt"}), ("read_file", {"path": ".git/config"}),
             ("edit_file", {"path": "app.py", "old": "not there", "new": "x"}),
             ("edit_file", {"path": "app.py", "old": "def calc(expr):", "new": "def calc(expr:"}),
             ("edit_file", {"path": "app.py"}), ("no_such_tool", {})]
    c = Claude(turn(calls), turn([("finish", {"summary": "gave up", "citations": []})])).install(monkeypatch)
    r = fixagent.fix(repo, [target(repo)])
    results = c.bodies[1]["messages"][-1]["content"]
    assert [x["is_error"] for x in results] == [True] * 9
    text = [x["content"] for x in results]
    assert "read-only" in text[0] and "occurs 0 times" in text[5] and "no longer parse" in text[6]
    assert "INVALID_INPUT" in text[7] and "unknown tool" in text[8]
    assert (repo / "test_app.py").read_text() == TEST and (repo / "app.py").read_text() == APP
    assert r["verdict"] == "no_changes"


def test_refusal_and_provider_errors_are_reported_not_hidden(repo, monkeypatch):
    Claude(turn([], text="I can't help with that.", stop="refusal")).install(monkeypatch)
    r = fixagent.fix(repo, [target(repo)])
    assert r["error"]["kind"] == "refusal" and r["verdict"] == "no_changes"
    for status, kind in ((401, "auth"), (404, "not_found"), (429, "rate_limit"), (500, "server")):
        Claude(status=status).install(monkeypatch)
        r = fixagent.fix(repo, [target(repo)])
        assert r["error"]["kind"] == kind, status


def test_a_stopped_run_keeps_its_evidence_but_is_marked_incomplete(repo, monkeypatch):
    stop = threading.Event()

    class Stopper(Claude):
        def handler(self, req):
            resp = super().handler(req)
            if len(self.bodies) == 2:
                stop.set()
            return resp
    Stopper(turn([edit()]), turn([("run_tests", {})]), turn([finish()])).install(monkeypatch)
    r = fixagent.fix(repo, [target(repo)], cancelled=stop)
    assert r["error"]["kind"] == "cancelled" and r["verdict"] == "incomplete"


def test_haiku_runs_without_the_fallback_beta(repo, monkeypatch):
    c = Claude(turn([edit()]), turn([finish()])).install(monkeypatch)
    fixagent.fix(repo, [target(repo)], model="claude-haiku-5-5")
    assert "fallbacks" not in c.bodies[0] and c.bodies[0]["model"] == "claude-haiku-5-5"


# ---- MITRE pack --------------------------------------------------------------------------------------------------------
def test_mitre_pack_is_real_and_links_come_from_mitre():
    src = mitre.source()
    assert src["attack"]["version"] and src["cwe"]["version"] and src["capec"]["version"]
    assert mitre.get("CWE-78")["name"].startswith("Improper Neutralization of Special Elements used in an OS Command")
    assert mitre.get("cwe 95")["id"] == "CWE-95" and mitre.get("T1059")["name"] == "Command and Scripting Interpreter"
    assert mitre.get("CWE-99999") is None and mitre.get("T9999") is None
    assert "CAPEC-88" in mitre.related("CWE-78") and "CWE-78" in mitre.related("CWE-78")
    b = mitre.brief("CWE-78", "T1059")
    assert b["cwe"]["mitigations"] and b["attack_from_mitre"] == []          # MITRE links no technique here
    assert b["paladin_technique"]["note"].startswith("Paladin's mapping")


# ---- end to end through the HTTP API on a real local git repository ----------------------------------------------------
EXEC_APP = 'def run(code):\n    exec(code)\n'
EXEC_OLD = '    exec(code)\n'
EXEC_NEW = '    raise ValueError("dynamic code execution is disabled")\n'
EXEC_TEST = ('import pytest\nimport app\n\n\ndef test_run_refuses_code():\n'
             '    with pytest.raises(ValueError):\n        app.run("x = 1")\n')
def test_endpoint_streams_the_run_and_commits_only_a_verified_fix(client, tmp_path, monkeypatch):
    from conftest import sign_in
    from app import harness, keys
    monkeypatch.setenv("APC_ALLOW_LOCAL", "1")
    monkeypatch.setenv("APC_ALLOW_LOCAL_TESTS", "1")
    monkeypatch.setenv("APC_OSV", "0")
    monkeypatch.setattr(fixagent, "docker_ready", lambda: False)
    monkeypatch.setattr(fixagent, "detect_tests",
                        lambda root: f"{shlex.quote(sys.executable)} -m pytest -x -q -p no:cacheprovider")
    r = tmp_path / "victim"
    r.mkdir()
    (r / "app.py").write_text(EXEC_APP)
    (r / "test_app.py").write_text(EXEC_TEST)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": __import__("os").environ["PATH"], "HOME": str(tmp_path)}
    for cmd in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "init"]):
        subprocess.run(["git", *cmd], cwd=r, env=env, check=True)
    sign_in(client)
    job = client.post("/api/harness/jobs", json={"repo_url": str(r)}).json()
    harness.wait(job["id"], 60)
    job = client.get(f"/api/harness/jobs/{job['id']}").json()
    open_ = [f for f in job["findings"] if f["rule"] == "code-exec" and not f.get("fixed")]
    assert open_, job["findings"]          # exec has no automatic fix, so it is the agent's to fix
    assert client.post("/api/agent/fix", json={}).status_code == 409          # no Claude key yet
    Claude(turn([edit(old=EXEC_OLD, new=EXEC_NEW)]), turn([("run_tests", {})]),
           turn([finish(("CWE-95",))])).install(monkeypatch)
    keys.set_many({"anthropic": "sk-ant-test-key-1234567"})
    try:
        with client.stream("POST", "/api/agent/fix", json={"finding_ids": [f["id"] for f in open_]}) as s:
            assert s.status_code == 200
            events = [json.loads(line[6:]) for line in s.iter_lines() if line.startswith("data: ")]
    finally:
        keys.clear()
    types = [e["type"] for e in events]
    assert types[0] == "start" and types[-1] == "verdict" and "tool" in types
    v = events[-1]
    assert v["verdict"] == "verified" and v["committed"] is True, v
    job = client.get(f"/api/harness/jobs/{job['id']}").json()
    assert "dynamic code execution is disabled" in job["diff"] and job["state"] == "ready"
    agent_fix = next(x for x in job["fixes"] if x["method"] == "agent")
    assert all(c["passed"] for c in agent_fix["checks"]), agent_fix["checks"]
    assert job["report"]["agent_runs"][-1]["verdict"] == "verified"
    assert next(f for f in job["findings"] if f["id"] == open_[0]["id"])["fixed"] is True


def test_a_free_form_request_checks_citations_for_existence_only(repo, monkeypatch):
    Claude(turn([edit()]), turn([finish(("CWE-88", "CAPEC-88"))])).install(monkeypatch)
    r = fixagent.fix(repo, [], instruction="harden calc")
    g = r["grounding"]
    assert g["ok"] and g["unrelated"] == [] and g["related_checked"] is False
    assert r["verdict"] == "verified" and "tests pass" in r["reason"]


def test_every_mitre_code_is_explained_in_plain_words_from_mitre_data():
    e = mitre.explain("CWE-89")
    assert e["short"] == "SQL Injection" and e["kind"] == "Weakness (MITRE CWE)"
    assert e["summary"].startswith("If exploited, an attacker can run their own code") and "change or delete your data" in e["summary"]
    assert e["what"].startswith("The product constructs all or part of an SQL command") and e["fix"]
    t = mitre.explain("T1190")
    assert t["name"] == "Exploit Public-Facing Application" and "getting into your system" in t["summary"]
    assert mitre.explain("M1038")["kind"].startswith("Mitigation") and mitre.explain("CAPEC-66")["summary"]
    assert mitre.explain("CWE-99999") is None


def test_explain_endpoint_batches_and_never_guesses(client):
    from conftest import sign_in
    sign_in(client)
    r = client.get("/api/mitre/explain", params={"ids": "CWE-78,T1059,CWE-99999,CWE-78"}).json()
    assert set(r["codes"]) == {"CWE-78", "T1059", "CWE-99999"}
    assert r["codes"]["CWE-78"]["short"] == "OS Command Injection"
    assert r["codes"]["CWE-99999"]["unknown"] is True and r["source"]["cwe"]["version"]


# ---- Windows spellings of .git and of test files ------------------------------------------------------------------------
@pytest.mark.parametrize("path", [r".git\config", ".git./config", ".git /config", ".GIT/config", "./.git/config",
                                  "a/../.git/config", "app.py::$DATA", "C:app.py", r"tests\test_x.py", "x/"])
def test_windows_path_spellings_cannot_reach_git_or_tests(tmp_path, path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("assert True\n")
    (tmp_path / "app.py").write_text("x = 1\n")
    s = fixagent.Session(root=tmp_path)
    old = "[core]" if "git" in path.lower() else "True" if "test" in path else "x"   # text the target really holds
    out, ok = s.call("edit_file", {"path": path, "old": old, "new": "y"})
    assert not ok, out
    assert (tmp_path / ".git" / "config").read_text() == "[core]\n"
    assert (tmp_path / "tests" / "test_x.py").read_text() == "assert True\n"


def test_an_edit_keeps_the_files_line_endings(tmp_path):
    (tmp_path / "lf.py").write_bytes(b"a = 1\nb = 2\n")
    (tmp_path / "crlf.py").write_bytes(b"a = 1\r\nb = 2\r\n")
    s = fixagent.Session(root=tmp_path)
    assert s.call("edit_file", {"path": "lf.py", "old": "b = 2", "new": "b = 3\nc = 4"})[1]
    assert s.call("edit_file", {"path": "crlf.py", "old": "b = 2", "new": "b = 3\nc = 4"})[1]
    assert (tmp_path / "lf.py").read_bytes() == b"a = 1\nb = 3\nc = 4\n"
    assert (tmp_path / "crlf.py").read_bytes() == b"a = 1\r\nb = 3\r\nc = 4\r\n"


def test_tests_that_cannot_start_are_not_run_rather_than_a_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("APC_ALLOW_LOCAL_TESTS", "1")
    monkeypatch.setattr(fixagent, "docker_ready", lambda: False)
    monkeypatch.setattr(fixagent, "detect_tests", lambda root: "pytest")
    monkeypatch.setattr(fixagent.shutil, "which", lambda name: str(tmp_path / "no-such-shell"))
    r = fixagent.run_tests(tmp_path)
    assert r.ran is False and "no shell" in r.reason


def test_search_refuses_patterns_that_can_backtrack_for_hours(tmp_path):
    (tmp_path / "a.py").write_text("a" * 40 + "!\nos.system(cmd)\n")
    s = fixagent.Session(root=tmp_path)
    for bad in ("(a+)+$", "(a|aa)*$", "(a*)*b", r"(\w+\s?)+$", "(x{1,9})+y", "(ab|a){2,}c"):
        out, ok = s.call("search_code", {"pattern": bad})
        assert not ok and "simpler pattern" in out, bad
    for good in (r"os\.system\(", r"eval\s*\(", "(foo|bar)", r"def \w+\(", "[a-z]+_key", r"(\d+)"):
        assert s.call("search_code", {"pattern": good})[1], good


def test_stored_steps_and_claim_do_not_keep_secrets_from_the_repository(repo, monkeypatch):
    (repo / "settings.py").write_text('API_KEY = "sk_live_0123456789abcdef"\n')
    Claude(turn([("read_file", {"path": "settings.py"})]),
           turn([("finish", {"summary": 'Found API_KEY = "sk_live_0123456789abcdef" in settings.py', "citations": []})])
           ).install(monkeypatch)
    r = fixagent.fix(repo, [target(repo)])
    stored = json.dumps({"steps": r["steps"], "claim": r["agent_claim"]})
    assert "sk_live_0123456789abcdef" not in stored and "***" in stored
