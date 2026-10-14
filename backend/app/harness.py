"""Repo harness: URL -> safe clone -> scan -> triage -> fix -> verify -> local branch -> (human approves) PR.

Repo code is never executed. Git runs with hooks off and symlinks off. The GitHub token is server env only."""
import base64
import difflib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import httpx

from . import ai, codescan, fixers, store

URL_RE = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]{1,100})/([A-Za-z0-9_.-]{1,100}?)(?:\.git)?/?$")
CLONE_TIMEOUT, MAX_REPO_BYTES, MAX_FIXES = 90, 150_000_000, 25
AUTHOR = ("Attack Path Compiler", "apc@users.noreply.github.com")
_threads: dict[int, threading.Thread] = {}


def data_root() -> Path:
    return Path(os.environ.get("DATA_DIR", "./data_dir")) / "jobs"


def parse_url(url: str) -> tuple[str, str, str]:
    """Return (owner, repo, clone_url). Only github.com https URLs (tests may allow a local path)."""
    m = URL_RE.match(url.strip())
    if m:
        return m[1], m[2], f"https://github.com/{m[1]}/{m[2]}.git"
    if os.environ.get("APC_ALLOW_LOCAL") == "1" and os.path.isdir(url):
        return "local", Path(url).name, url
    raise ValueError("only https://github.com/<owner>/<repo> links are accepted")


def _git(args: list[str], cwd: Path | None = None, token: str | None = None, timeout: int = 60):
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "/tmp"), "GIT_TERMINAL_PROMPT": "0",
           "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"}
    if token:
        hdr = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
                   GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {hdr}")
    base = ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.symlinks=false", "-c", "protocol.ext.allow=never"]
    if os.environ.get("APC_ALLOW_LOCAL") != "1":
        base += ["-c", "protocol.file.allow=never"]
    r = subprocess.run(base + args, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {r.stderr.strip()[:200]}")
    return r.stdout


def _dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink())


def load_files(root: Path) -> list[dict]:
    out = []
    for p in sorted(root.rglob("*")):
        if ".git" in p.relative_to(root).parts or p.is_symlink() or not p.is_file():
            continue
        if p.stat().st_size > codescan.MAX_FILE_BYTES:
            continue
        try:
            out.append({"path": p.relative_to(root).as_posix(), "content": p.read_text(encoding="utf-8")})
        except (UnicodeDecodeError, OSError):
            continue
    return out


# ---- job storage ----
def _ensure() -> None:
    store.run("""CREATE TABLE IF NOT EXISTS jobs(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ws INTEGER NOT NULL, repo_url TEXT NOT NULL, state TEXT NOT NULL,
        log TEXT NOT NULL DEFAULT '[]', findings TEXT NOT NULL DEFAULT '[]', fixes TEXT NOT NULL DEFAULT '[]',
        branch TEXT NOT NULL DEFAULT '', pr_url TEXT NOT NULL DEFAULT '', diff TEXT NOT NULL DEFAULT '',
        ai_used INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '', created REAL NOT NULL,
        updated REAL NOT NULL)""")


def _upd(jid: int, **cols) -> None:
    cols["updated"] = time.time()
    store.run(f"UPDATE jobs SET {','.join(k + '=?' for k in cols)} WHERE id=?", (*cols.values(), jid))


def _log(jid: int, msg: str) -> None:
    r = store.q("SELECT log FROM jobs WHERE id=?", (jid,))
    lg = json.loads(r[0]["log"]) + [{"t": round(time.time(), 1), "msg": msg[:300]}]
    _upd(jid, log=json.dumps(lg[-200:]))


def get(ws: int, jid: int) -> dict:
    _ensure()
    r = store.q("SELECT * FROM jobs WHERE id=? AND ws=?", (jid, ws))
    if not r:
        raise KeyError(jid)
    d = dict(r[0])
    for k in ("log", "findings", "fixes"):
        d[k] = json.loads(d[k])
    d["ai_used"] = bool(d["ai_used"])
    return d


def list_jobs(ws: int) -> list[dict]:
    _ensure()
    return [{k: v for k, v in get(ws, r["id"]).items() if k not in ("log", "diff", "findings")}
            for r in store.q("SELECT id FROM jobs WHERE ws=? ORDER BY id DESC LIMIT 30", (ws,))]


def start(ws: int, url: str) -> dict:
    _ensure()
    owner, repo, clone_url = parse_url(url)
    busy = store.q("SELECT 1 FROM jobs WHERE ws=? AND state IN ('queued','cloning','scanning','fixing')", (ws,))
    if busy:
        raise RuntimeError("a job is already running for this workspace")
    now = time.time()
    jid = store.run("INSERT INTO jobs(ws,repo_url,state,created,updated) VALUES(?,?,?,?,?)",
                    (ws, f"{owner}/{repo}" if owner != "local" else clone_url, "queued", now, now))
    t = threading.Thread(target=_run, args=(ws, jid, owner, repo, clone_url), daemon=True)
    _threads[jid] = t
    t.start()
    return get(ws, jid)


def wait(jid: int, timeout: float = 60) -> None:
    t = _threads.get(jid)
    if t:
        t.join(timeout)


def _run(ws: int, jid: int, owner: str, repo: str, clone_url: str) -> None:
    work = data_root() / str(jid)
    try:
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        src = work / "repo"
        _upd(jid, state="cloning")
        _log(jid, f"cloning {owner}/{repo} (depth 1, hooks off, symlinks off)")
        token = os.environ.get("GITHUB_TOKEN") if owner != "local" else None
        _git(["clone", "--depth", "1", "--no-tags", "--single-branch", "--no-recurse-submodules",
              clone_url, str(src)], token=token, timeout=CLONE_TIMEOUT)
        if _dir_size(src) > MAX_REPO_BYTES:
            raise RuntimeError("repository too large")
        _upd(jid, state="scanning")
        files = load_files(src)
        total = sum(1 for p in src.rglob("*") if p.is_file() and ".git" not in p.relative_to(src).parts)
        kept = codescan.accept_files(files)
        exts = sorted({Path(f["path"]).suffix or f["path"] for f in kept})
        _log(jid, f"repo has {total} files; {len(kept)} are scannable source "
                  f"({', '.join(exts) or 'none'}); {total - len(kept)} skipped (docs, binaries, lockfiles, "
                  "vendored or oversized)")
        if not kept:
            sample = ", ".join(sorted(Path(f["path"]).name for f in files)[:6])
            codescan.persist(ws, f"{owner}/{repo}", [], False, 0)
            _upd(jid, state="done", fixes="[]")
            _log(jid, f"nothing to scan: no source files in a supported language (found: {sample or 'no text files'})")
            return
        findings, ai_used, n = codescan.scan(files)
        _log(jid, f"scanned {n} files: {len(findings)} candidate findings"
                  f"{' (Haiku triaged)' if ai_used else ' (static only)' if findings else ''}")
        codescan.persist(ws, f"{owner}/{repo}", findings, ai_used, n)
        _upd(jid, state="fixing", ai_used=int(ai_used))
        fixes = _fix_all(jid, src, files, findings)
        for f in findings:
            f.pop("context", None)
        _upd(jid, findings=json.dumps(findings))
        if not fixes:
            _upd(jid, state="done", fixes="[]")
            live = [f for f in findings if f["exploitable"] is not False]
            _log(jid, "clean: no findings, nothing to fix" if not findings else
                 f"{len(findings)} candidate(s), {len(findings) - len(live)} judged not exploitable, "
                 f"{len(live)} need a manual fix (no safe automatic patch)")
            return
        branch = f"apc/fix-{jid}-{int(time.time())}"
        _git(["checkout", "-q", "-b", branch], cwd=src)
        for p, new in _final_contents(files, fixes).items():
            (src / p).write_text(new, encoding="utf-8")
        _git(["add", "-A"], cwd=src)
        msg = f"Fix {len(fixes)} security finding(s) found by Attack Path Compiler"
        _git(["-c", f"user.name={AUTHOR[0]}", "-c", f"user.email={AUTHOR[1]}", "commit", "-q", "-m", msg], cwd=src)
        diff = _git(["diff", "HEAD~1", "HEAD"], cwd=src)
        _upd(jid, state="ready", branch=branch, diff=diff[:400_000],
             fixes=json.dumps([{k: v for k, v in x.items() if k != "content"} for x in fixes]))
        _log(jid, f"committed {len(fixes)} fix(es) on local branch {branch}; waiting for human approval to open PR")
    except Exception as e:  # noqa: BLE001 - recorded, never leaked as a stack trace
        _upd(jid, state="failed", error=str(e)[:300])
        _log(jid, f"failed: {str(e)[:200]}")


def _fix_all(jid: int, src: Path, files: list[dict], findings: list[dict]) -> list[dict]:
    contents = {f["path"]: f["content"] for f in files}
    done, seen = [], set()
    # fix bottom-up per file so earlier line numbers stay valid
    order = sorted((f for f in findings if f["exploitable"] is not False),
                   key=lambda f: (f["file"], -f["line"]))
    for f in order[:MAX_FIXES * 2]:
        if len(done) >= MAX_FIXES:
            break
        res = fixers.try_fix(contents[f["file"]], f)
        if not res:
            _log(jid, f"no safe fix for {f['rule']} at {f['file']}:{f['line']}")
            continue
        contents[f["file"]] = res["content"]
        f["fixed"] = True
        done.append({"id": f["id"], "file": f["file"], "line": f["line"], "rule": f["rule"], "cwe": f["cwe"],
                     "technique": f["technique"], "method": res["method"], "explanation": res["explanation"],
                     "content": res["content"]})
        _log(jid, f"fixed {f['rule']} at {f['file']}:{f['line']} via {res['method']}")
    return done


def _final_contents(files: list[dict], fixes: list[dict]) -> dict[str, str]:
    last: dict[str, str] = {}
    for fx in fixes:  # contents were applied cumulatively in order, so the last one per file is final
        last[fx["file"]] = fx["content"]
    return last


def patch_text(ws: int, jid: int) -> str:
    return get(ws, jid)["diff"]


# ---- GitHub ----
def gh_api(method: str, path: str, token: str, body: dict | None = None) -> dict:
    r = httpx.request(method, f"https://api.github.com{path}", json=body, timeout=30, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"})
    if r.status_code >= 400:
        raise RuntimeError(f"GitHub {method} {path} -> {r.status_code}")
    return r.json()


def pr_body(job: dict) -> str:
    rows = "\n".join(f"- `{x['file']}:{x['line']}` {x['rule']} ({x['cwe']}, ATT&CK {x['technique']}): "
                     f"{x['explanation']} _[{x['method']}]_" for x in job["fixes"])
    ai_note = "Claude Haiku was used to triage findings and/or draft patches. " if job["ai_used"] or any(
        x["method"] == "haiku" for x in job["fixes"]) else ""
    return (f"## Automated security fixes\n\n{rows}\n\n### How these were verified\n"
            "Each patch was checked by code: the matched text occurs exactly once, the file still parses, the "
            "triggering rule no longer matches and no new findings appear. **Tests were not run - please review "
            "and run CI before merging.**\n\n"
            f"{ai_note}Generated by Attack Path Compiler (synthetic-data hackathon project).")


def open_pr(ws: int, jid: int) -> dict:
    job = get(ws, jid)
    if job["state"] != "ready":
        raise RuntimeError(f"job is {job['state']}, not ready")
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise PermissionError("GITHUB_TOKEN is not configured on the server; download the patch instead")
    owner, repo = job["repo_url"].split("/", 1)
    src = data_root() / str(jid) / "repo"
    info = gh_api("GET", f"/repos/{owner}/{repo}", token)
    base = info["default_branch"]
    head_repo, head_ref = (owner, repo), job["branch"]
    if not info.get("permissions", {}).get("push"):
        me = gh_api("GET", "/user", token)["login"]
        gh_api("POST", f"/repos/{owner}/{repo}/forks", token, {})
        for _ in range(15):
            try:
                gh_api("GET", f"/repos/{me}/{repo}", token)
                break
            except RuntimeError:
                time.sleep(2)
        head_repo, head_ref = (me, repo), f"{me}:{job['branch']}"
    _git(["push", f"https://github.com/{head_repo[0]}/{head_repo[1]}.git", f"HEAD:refs/heads/{job['branch']}"],
         cwd=src, token=token, timeout=120)
    pr = gh_api("POST", f"/repos/{owner}/{repo}/pulls", token, {
        "title": f"Security: fix {len(job['fixes'])} finding(s) (Attack Path Compiler)", "head": head_ref,
        "base": base, "body": pr_body(job), "maintainer_can_modify": True})
    _upd(jid, state="pr_opened", pr_url=pr["html_url"])
    _log(jid, f"opened PR {pr['html_url']}")
    return get(ws, jid)


def config() -> dict:
    return {"github_enabled": bool(os.environ.get("GITHUB_TOKEN")), "ai_enabled": ai.enabled()}
