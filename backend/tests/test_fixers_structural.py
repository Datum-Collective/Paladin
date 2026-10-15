"""Fixes a model is told to refuse (they cannot keep behaviour byte-identical) but that have one safe form.
Regression for paladin-demo: eval, os.system and a timing-unsafe key check were left as "no safe fix"."""
import subprocess
import sys

from app import codescan, fixers

SERVER = '''"""Demo."""
import os

from flask import Flask, jsonify, request

app = Flask(__name__)
API_KEY = os.environ.get("API_KEY", "")


@app.get("/c")
def c():
    if request.headers.get("X-API-Key") != API_KEY:
        return "no", 401
    return "ok"


@app.post("/calc")
def calc():
    return jsonify(result=eval(request.json["expr"]))


@app.post("/ping")
def ping():
    host = request.json["host"]
    os.system("ping -c 1 " + host)
    return jsonify(ok=True)
'''


def finding(src, rule, needle):
    line = next(i for i, ln in enumerate(src.split("\n"), 1) if needle in ln)
    return {"file": "app/server.py", "rule": rule, "line": line, "cwe": "", "technique": "",
            "line_hash": codescan.line_hash(src.split("\n")[line - 1])}


def fix_all(src):
    fs = [finding(src, "shell-injection", "os.system"), finding(src, "code-exec", "eval("),
          finding(src, "ai-auth", "!= API_KEY")]
    out = src
    for f in sorted(fs, key=lambda f: -f["line"]):      # the harness order: bottom-up per file
        r = fixers.try_fix(out, f)
        assert r and r["method"] == "rule", f["rule"]
        out = r["content"]
    return out


def test_all_three_are_fixed_without_a_model_and_the_file_parses():
    out = fix_all(SERVER)
    compile(out, "server.py", "exec")
    assert "os.system" not in out and "eval(" not in out.replace("_safe_arith(", "")
    assert "hmac.compare_digest" in out and "subprocess.run([*shlex.split('ping -c 1'), host]" in out
    assert out.count("import shlex") == out.count("import subprocess") == out.count("import hmac") == 1
    assert not [f for f in codescan.static_scan([{"path": "app/server.py", "content": out}])
                if f["rule"] in ("shell-injection", "code-exec")]


def test_safe_arith_keeps_arithmetic_and_refuses_code():
    ns = {}
    exec(fixers._SAFE_ARITH, ns)
    f = ns["_safe_arith"]
    assert f("2*3+1") == 7 and f("-(4 / 2)") == -2 and f("7 // 2 % 3") == 0
    for bad in ("__import__('os').getcwd()", "open('/etc/passwd')", "().__class__", "9**999999", "x"):
        try:
            f(bad)
        except (ValueError, SyntaxError):
            continue
        raise AssertionError(f"{bad!r} was evaluated")


def test_patched_ping_cannot_inject_a_command(tmp_path):
    out = fix_all(SERVER)
    marker = tmp_path / "pwned"
    line = next(ln.strip() for ln in out.split("\n") if "subprocess.run(" in ln)
    code = (f"import shlex, subprocess\nhost = {('127.0.0.1 -c 1 -W 1; touch ' + str(marker))!r}\n"
            f"{line.replace('ping -c 1', 'true')}\n")
    subprocess.run([sys.executable, "-c", code], check=False, capture_output=True)
    assert not marker.exists()


def test_timing_fix_keeps_missing_header_rejected():
    out = fix_all(SERVER)
    line = next(ln.strip() for ln in out.split("\n") if "compare_digest" in ln)
    cond = line[len("if "):-1]
    import hmac
    for given, key, rejected in ((None, "", True), ("", "", False), ("a", "b", True), ("k", "k", False)):
        ns = {"hmac": hmac, "API_KEY": key, "request": type("R", (), {"headers": {"X-API-Key": given} if given is not None else {}})}
        assert bool(eval(cond, ns)) is rejected, (given, key)   # noqa: S307 - evaluating our own fixed condition
