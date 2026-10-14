"""Repo harness: URL -> safe clone -> scan -> triage -> fix -> verify -> local branch -> (human approves) PR.

Repo code is never executed. Git runs with hooks off and symlinks off. The GitHub token is server env only."""
import base64
import contextvars
import difflib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import ai, codescan, fixers, keys, supa
from . import config as settings

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
    # local folders are read in place by the desktop app only; a web server never scans its own disk on request
    if (os.environ.get("APC_ALLOW_LOCAL") == "1" or os.environ.get("DESKTOP_MODE") == "1") and os.path.isdir(url):
        return "local", Path(url).name, url
    raise ValueError("only https://github.com/<owner>/<repo> links are accepted")


def _git(args: list[str], cwd: Path | None = None, token: str | None = None, timeout: int = 60,
         allow_file: bool = False):
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "/tmp"), "GIT_TERMINAL_PROMPT": "0",
           "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"}
    if token:
        hdr = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
                   GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {hdr}")
    base = ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.symlinks=false", "-c", "protocol.ext.allow=never"]
    # the file protocol is blocked except for the one clone of a folder the user explicitly chose (desktop only)
    base += ["-c", f"protocol.file.allow={'always' if allow_file or os.environ.get('APC_ALLOW_LOCAL') == '1' else 'never'}"]
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


BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".pdf", ".zip", ".gz", ".tar", ".woff",
              ".woff2", ".ttf", ".eot", ".mp4", ".mp3", ".pyc", ".so", ".dll", ".exe", ".bin", ".csv", ".parquet"}
DOC_EXT = {".md", ".txt", ".rst", ".adoc"}


def _json_default(key: str):
    return {} if key == "report" else []


def _skip_reason(rel: str, size: int, kept: set[str]) -> str | None:
    """None when the file was scanned, otherwise the reason it was not."""
    low = rel.lower()
    if rel in kept:
        return None
    if any(d in low + "/" or low.startswith(d) or ("/" + d) in "/" + low for d in codescan.SKIP_DIRS):
        return "vendored or build output"
    ext = Path(low).suffix
    base = Path(low).name
    if base.startswith(".env") or base.endswith((".pem", ".key", "id_rsa")):
        return "credential files (deliberately not read)"
    if low.endswith(codescan.SKIP_FILES) or ext in (".map", ".lock"):
        return "lockfiles, minified, source maps"
    if ext in DOC_EXT:
        return "docs"
    if ext in BINARY_EXT:
        return "binary or media"
    if ext in codescan.CODE_EXT:
        return "oversized or over the scan limit" if size > codescan.MAX_FILE_BYTES else "over the scan limit"
    return "other file types"


def coverage(src: Path, kept: list[dict], findings: list[dict], ai_stats: dict, ai_on: bool) -> dict:
    kept_paths = {f["path"] for f in kept}
    skipped: dict[str, dict] = {}
    total = 0
    vendored = {d.rstrip("/") for d in codescan.SKIP_DIRS}

    def note(why: str, n: int, example: str) -> None:
        d = skipped.setdefault(why, {"count": 0, "examples": []})
        d["count"] += n
        if example not in d["examples"] and len(d["examples"]) < 4:
            d["examples"].append(example)

    for root, dirs, names in os.walk(src):
        dirs[:] = [d for d in dirs if d != ".git"]
        rel_root = Path(root).relative_to(src)
        top = rel_root.parts[0] if rel_root.parts else ""
        if rel_root.parts and rel_root.parts[-1] in vendored:   # count without stat-ing every vendored file
            n = sum(len(fs) for _, _, fs in os.walk(root))
            total += n
            note("vendored or build output", n, rel_root.as_posix())
            dirs[:] = []
            continue
        for name in names:
            p = Path(root) / name
            if p.is_symlink():
                continue
            total += 1
            rel = (rel_root / name).as_posix()
            why = _skip_reason(rel, p.stat().st_size, kept_paths)
            if why:
                note(why, 1, top or name)
    judged_no = sum(1 for f in findings if f["exploitable"] is False)
    return {
        "files_total": total, "scanned": len(kept), "lines_scanned": ai_stats.get("lines", 0),
        "skipped": skipped, "scanned_files": sorted(kept_paths)[:80],
        "rules": [{"id": r[0], "title": r[5], "cwe": r[2]} for r in codescan.RULES],
        "candidates": sum(1 for f in findings if f["triaged_by"] != "haiku-review"),
        "judged_not_exploitable": judged_no,
        "ai": {"enabled": ai_on, "triage": ai_stats.get("triage", False),
               "review_files": ai_stats.get("files_reviewed", 0), "review_findings": ai_stats.get("findings", 0),
               "claims_rejected": ai_stats.get("claims_rejected", 0),
               "review_truncated": ai_stats.get("truncated", [])},
        "limits": "Pattern rules plus an AI review of up to 10 files; not a full static-analysis or "
                  "dependency audit. Repo code is never executed.",
    }


# ---- job storage (Supabase, as the signed-in user) ----
RUNNING = ("queued", "cloning", "scanning", "fixing")
STALE_S = 600   # a running job with no progress for this long, and no thread here, was cut off (quit, crash, deploy)
INTERRUPTED = "Interrupted: the app closed before this scan finished. Retry to run it again."
_JSON_COLS = ("log", "findings", "fixes", "report")


def ensure() -> None:
    """Kept for callers from the SQLite days; the schema now comes from the Supabase migrations."""


def _live() -> set[int]:
    return {jid for jid, t in list(_threads.items()) if t.is_alive()}


def effective_state(row: dict) -> str:
    """A scan runs in a thread of the process that started it. If that process is gone, the row still says
    running: report it as failed so the user can retry instead of watching it spin forever."""
    if (row.get("state") in RUNNING and row.get("id") not in _live()
            and time.time() - (row.get("updated") or 0) > STALE_S):
        return "failed"
    return row.get("state", "")


def recover_interrupted(max_age_s: float = STALE_S) -> int:
    """Mark the current user's cut-off scans failed. Jobs this process is running are never touched."""
    cutoff = time.time() - max_age_s
    rows = supa.select("jobs", {"state": supa.in_(RUNNING), "updated": supa.lt(cutoff)}, columns="id")
    ids = [r["id"] for r in rows if r["id"] not in _live()]
    if ids:
        supa.update("jobs", {"id": supa.in_(ids), "state": supa.in_(RUNNING)},
                    {"state": "failed", "error": INTERRUPTED, "updated": time.time()}, returning=None)
    return len(ids)


def _upd(jid: int, **cols) -> None:
    cols["updated"] = time.time()
    for k in _JSON_COLS:
        if isinstance(cols.get(k), str):
            cols[k] = json.loads(cols[k])
    if "ai_used" in cols:
        cols["ai_used"] = bool(cols["ai_used"])
    supa.update("jobs", {"id": supa.eq(jid)}, cols, returning=None)


def _log(jid: int, msg: str) -> None:
    r = supa.first("jobs", {"id": supa.eq(jid)}, columns="log")
    lg = (r["log"] if r and isinstance(r["log"], list) else []) + [{"t": round(time.time(), 1), "msg": msg[:300]}]
    _upd(jid, log=lg[-200:])


def _shape(r: dict) -> dict:
    d = dict(r)
    d.pop("user_id", None)
    for k in _JSON_COLS:
        if k in d:
            want = dict if k == "report" else list
            d[k] = d[k] if isinstance(d[k], want) else _json_default(k)
    d["ai_used"] = bool(d.get("ai_used"))
    d["state"] = effective_state(d)
    if d["state"] == "failed" and r.get("state") in RUNNING:
        d["error"] = INTERRUPTED
    return d


def get(ws: int, jid: int) -> dict:
    r = supa.first("jobs", {"id": supa.eq(jid), "ws": supa.eq(ws)})
    if not r:
        raise KeyError(jid)
    return _shape(r)


def list_jobs(ws: int) -> list[dict]:
    cols = "id,ws,repo_url,state,fixes,branch,pr_url,ai_used,error,created,updated"
    return [_shape(r) for r in supa.select("jobs", {"ws": supa.eq(ws)}, columns=cols, order="id.desc", limit=30)]


def start(ws: int, url: str, *, token: str | None = None) -> dict:
    """Start a scan. `token` is the credential for cloning a private repo: on the web, a short-lived GitHub App
    token limited to this one repo (resolved by the caller from the user's own installation); on the desktop,
    None means the user's own token from the keychain."""
    owner, repo, clone_url = parse_url(url)
    cleanup_old()
    busy = [r for r in supa.select("jobs", {"ws": supa.eq(ws), "state": supa.in_(RUNNING)}, columns="id,state,updated")
            if effective_state(r) in RUNNING]
    if busy:
        raise RuntimeError("a job is already running for this workspace")
    now = time.time()
    jid = supa.insert("jobs", {"ws": ws, "user_id": supa.user_id(), "state": "queued", "created": now, "updated": now,
                               "repo_url": f"{owner}/{repo}" if owner != "local" else clone_url},
                      returning="id")[0]["id"]
    # the thread keeps this request's Supabase session (context copy), so its writes are still the user's own
    ctx = contextvars.copy_context()
    t = threading.Thread(target=ctx.run, args=(_run, ws, jid, owner, repo, clone_url, token), daemon=True)
    _threads[jid] = t
    t.start()
    return get(ws, jid)


def wait(jid: int, timeout: float = 60) -> None:
    t = _threads.get(jid)
    if t:
        t.join(timeout)


def _run(ws: int, jid: int, owner: str, repo: str, clone_url: str, token: str | None = None) -> None:
    work = data_root() / str(jid)
    if token is None and owner != "local":
        token = keys.get("GITHUB_TOKEN")   # desktop only; always None on the web server
    try:
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        src = work / "repo"
        _upd(jid, state="cloning")
        _log(jid, f"cloning {owner}/{repo} (depth 1, hooks off, symlinks off)")
        local = owner == "local"
        # a file:// URL makes git copy objects (no hardlinks into the user's repo) and honour --depth
        source = Path(clone_url).resolve().as_uri() if local else clone_url
        _git(["clone", "--depth", "1", "--no-tags", "--single-branch", "--no-recurse-submodules",
              source, str(src)], token=token, timeout=CLONE_TIMEOUT, allow_file=local)
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
            _upd(jid, state="done", fixes="[]",
                 report=json.dumps(coverage(src, [], [], {}, ai.enabled())))
            _log(jid, f"nothing to scan: no source files in a supported language (found: {sample or 'no text files'})")
            return
        _log(jid, f"checking {len(kept)} files against {len(codescan.RULES)} rules"
                  f"{' and an AI review of the most exposed files' if ai.enabled() else ' (AI off)'}")
        findings, ai_used, n, stats = codescan.scan_full(files)
        rep = coverage(src, kept, findings, stats, ai.enabled())
        _upd(jid, report=json.dumps(rep))
        _log(jid, f"scanned {n} files, {rep['lines_scanned']} lines against {len(rep['rules'])} rules: "
                  f"{rep['candidates']} rule hit(s), {stats['findings']} AI-review finding(s), "
                  f"{rep['judged_not_exploitable']} judged not exploitable")
        codescan.persist(ws, f"{owner}/{repo}", findings, ai_used, n)
        _upd(jid, state="fixing", ai_used=int(ai_used))
        fixes = _fix_all(jid, src, files, findings)
        for f in findings:
            f.pop("context", None)
        _upd(jid, findings=json.dumps(findings))
        if not fixes:
            _upd(jid, state="done", fixes="[]")
            live = [f for f in findings if f["exploitable"] is not False]
            if not findings:
                msg = f"no issues found: {len(rep['rules'])} rules over {rep['lines_scanned']} lines in {n} files"
                if stats["files_reviewed"]:
                    msg += f", plus AI review of {stats['files_reviewed']} files"
                if stats["truncated"]:
                    msg += f" ({len(stats['truncated'])} too long to review in full)"
                _log(jid, msg + " (this is not a proof of safety)")
                return
            _log(jid, f"{len(findings)} candidate(s), {len(findings) - len(live)} judged not exploitable, "
                 f"{len(live)} need a manual fix (no safe automatic patch)")
            return
        branch = f"apc/fix-{jid}-{int(time.time())}"
        _git(["checkout", "-q", "-b", branch], cwd=src)
        for p, new in _final_contents(files, fixes).items():
            (src / p).write_text(new, encoding="utf-8")
        verification = _verify_tree(src, files, fixes, findings)
        rep["verification"] = verification
        _upd(jid, report=json.dumps(rep))
        _log(jid, f"verified on disk: {verification['python_files_compiled']}/{verification['python_files_changed']} "
                  f"changed Python file(s) compile; findings {verification['findings_before']} -> "
                  f"{verification['findings_after']}")
        _git(["add", "-A"], cwd=src)
        msg = f"Fix {len(fixes)} security finding(s) found by Attack Path Compiler"
        _git(["-c", f"user.name={AUTHOR[0]}", "-c", f"user.email={AUTHOR[1]}", "commit", "-q", "-m", msg], cwd=src)
        diff = _git(["diff", "HEAD~1", "HEAD"], cwd=src)
        _upd(jid, state="ready", branch=branch, diff=diff[:400_000],
             fixes=json.dumps([{k: v for k, v in x.items() if k != "content"} for x in fixes]))
        _log(jid, f"committed {len(fixes)} fix(es) on local branch {branch}; waiting for human approval to open PR")
    except Exception as e:  # noqa: BLE001 - recorded, never leaked as a stack trace
        msg = str(e).replace(token, "***") if token else str(e)
        try:
            _upd(jid, state="failed", error=msg[:300])
            _log(jid, f"failed: {msg[:200]}")
        except Exception:  # noqa: BLE001 - e.g. the session expired mid-scan: the row goes stale, shows as failed
            pass


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
                     "checks": res["checks"], "content": res["content"]})
        _log(jid, f"fixed {f['rule']} at {f['file']}:{f['line']} via {res['method']}")
    return done


def _verify_tree(src: Path, files: list[dict], fixes: list[dict], findings: list[dict]) -> dict:
    """Independent re-check of what is now ON DISK: compile changed Python, then re-scan the changed files."""
    changed = sorted({f["file"] for f in fixes})
    py = [p for p in changed if p.endswith(".py")]
    compiled = 0
    for p in py:
        try:
            compile((src / p).read_text(encoding="utf-8"), p, "exec")
            compiled += 1
        except (SyntaxError, ValueError, OSError):
            pass
    now = []
    for p in changed:
        try:
            now.append({"path": p, "content": (src / p).read_text(encoding="utf-8")})
        except OSError:
            pass
    after = codescan.static_scan(now) if now else []
    before = [f for f in findings if f["file"] in changed and f["triaged_by"] != "haiku-review"]
    fixed_rules = {f["rule"] for f in fixes}
    still = sorted({a["rule"] for a in after if a["rule"] in fixed_rules})
    return {"changed_files": len(changed), "python_files_changed": len(py), "python_files_compiled": compiled,
            "findings_before": len(before), "findings_after": len(after), "fixed_rules_still_matching": still}


def patched_file(ws: int, jid: int, path: str) -> dict:
    """Content of a file as it is on the job's branch, restricted to files the job actually changed."""
    job = get(ws, jid)
    changed = {f["file"] for f in job["fixes"]}
    if path not in changed:
        raise KeyError(path)
    root = (data_root() / str(jid) / "repo").resolve()
    target = (root / path).resolve()
    if root not in target.parents or not target.is_file() or target.is_symlink():
        raise KeyError(path)
    text = target.read_text(encoding="utf-8")
    import re as _re
    changed_lines: list[int] = []
    for m in _re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", _file_diff(job["diff"], path), _re.M):
        start, n = int(m[1]), int(m[2] or 1)
        changed_lines += list(range(start, start + n))
    return {"path": path, "content": text[:400_000], "changed_lines": sorted(set(changed_lines))}


def _file_diff(diff: str, path: str) -> str:
    parts = diff.split("diff --git ")
    for part in parts:
        if part.startswith(f"a/{path} b/{path}"):
            return part
    return ""


def cleanup_old(max_age_s: float = 86400) -> None:
    """Delete job clones nobody is waiting on. Called when a new job starts, so disk use stays bounded."""
    root = data_root()
    if not root.exists():
        return
    now = time.time()
    for d in root.iterdir():
        try:
            if d.is_dir() and now - d.stat().st_mtime > max_age_s:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def _final_contents(files: list[dict], fixes: list[dict]) -> dict[str, str]:
    last: dict[str, str] = {}
    for fx in fixes:  # contents were applied cumulatively in order, so the last one per file is final
        last[fx["file"]] = fx["content"]
    return last


def patch_text(ws: int, jid: int) -> str:
    return get(ws, jid)["diff"]


# ---- GitHub ----
def pr_body(job: dict) -> str:
    # the job row is the user's own and could have been edited through the API: read every field defensively
    fixes = [x for x in job["fixes"] if isinstance(x, dict)]
    rows = "\n".join(f"- `{x.get('file')}:{x.get('line')}` {x.get('rule')} ({x.get('cwe')}, ATT&CK {x.get('technique')}): "
                     f"{x.get('explanation')} _[{x.get('method')}]_"
                     f"{' **AI-drafted: review the semantics carefully**' if x.get('method') == 'haiku' else ''}"
                     for x in fixes)
    ai_note = "Claude Haiku was used to triage findings and/or draft patches. " if job["ai_used"] or any(
        x.get("method") == "haiku" for x in fixes) else ""
    return (f"## Automated security fixes\n\n{rows}\n\n### How these were verified\n"
            "Each patch was checked by code: the matched text occurs exactly once, the file still parses, the "
            "triggering rule no longer matches and no new findings appear. **Tests were not run - please review "
            "and run CI before merging.**\n\n"
            f"{ai_note}Generated by Attack Path Compiler (synthetic-data hackathon project).")


class JobNotFound(Exception):
    pass


def pr_request(ws: int, jid: int) -> dict:
    """What a pull request for this job would contain: the final content of every file the job changed, read from
    the job's working copy. The PR itself is opened by github_access.open_job_pr (fixes branch, fast-forward only)."""
    try:
        job = get(ws, jid)
    except KeyError:
        raise JobNotFound(jid) from None
    if job["state"] != "ready":
        raise RuntimeError(f"job is {job['state']}, not ready")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", job["repo_url"]):
        raise RuntimeError("Pull requests are only available for GitHub repositories. Download the patch instead.")
    root = (data_root() / str(jid) / "repo").resolve()
    files = {}
    for path in sorted({f["file"] for f in job["fixes"] if isinstance(f, dict) and isinstance(f.get("file"), str)}):
        target = (root / path).resolve()
        if root not in target.parents or not target.is_file() or target.is_symlink():
            raise RuntimeError("This scan's working copy was cleared. Run the scan again to open a pull request.")
        files[path] = target.read_text(encoding="utf-8")
    if not files:
        raise RuntimeError("This scan has no fixes to send.")
    owner, repo = job["repo_url"].split("/", 1)
    return {"job": job, "owner": owner, "repo": repo, "files": files,
            "title": f"Security: fix {len(job['fixes'])} finding(s) (Attack Path Compiler)", "body": pr_body(job),
            "commit_message": f"Fix {len(job['fixes'])} security finding(s) found by Attack Path Compiler"}


def mark_pr_opened(ws: int, jid: int, url: str) -> dict:
    _upd(jid, state="pr_opened", pr_url=url)
    _log(jid, f"opened PR {url} from the fixes branch")
    return get(ws, jid)


def config() -> dict:
    gh = settings.GITHUB_ENABLED if not settings.desktop_mode() else bool(keys.get("GITHUB_TOKEN"))
    return {"github_enabled": gh, "ai_enabled": ai.enabled()}


def wipe(ws: int) -> None:
    for r in supa.select("jobs", {"ws": supa.eq(ws)}, columns="id"):
        shutil.rmtree(data_root() / str(r["id"]), ignore_errors=True)
