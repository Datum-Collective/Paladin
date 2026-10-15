"""Code remediation: real, reviewable, reversible edits for findings a scan produced.

A remediation for code findings is a unified diff computed from the scanned source, not a runbook:
  plan      re-derive the fix for exactly the selected findings from the files as they were scanned, check each fix
            (parses, rule stops matching, nothing new introduced) and build one patch with `git diff`.
  apply     local folder: `git apply --check` first, then `git apply` (all or nothing). A file the user changed in
            the meantime makes the check fail and nothing is written. GitHub repo: the same files go to the fixes
            branch as a pull request; nothing is claimed applied until GitHub accepted it.
  verify    read the files as they are NOW, make sure they still parse and that the rules the fix targeted match
            no more often than in the intended result. Tests are never run (repository code is not executed).
  rollback  `git apply -R` with the same check, so edits made after the fix are never overwritten.

Nothing outside the target folder is touched, and nothing is written when any step of the check fails.
"""
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from . import codescan, config, fixers, harness, supa

SETTLED = ("ready", "done", "pr_opened")
MAX_PATCH = 400_000
_FID = re.compile(r"^code:(?:sink:)?(f\d+)$")


class FixError(Exception):
    """A problem the user can act on; the message is safe to show."""


def _env() -> dict:
    """Git environment that cannot be steered by the repository: no repo-supplied or user-global config, no
    fsmonitor or hooks, and a scratch HOME so a .gitconfig inside the folder is never read."""
    return {"PATH": os.environ.get("PATH", ""), "HOME": tempfile.gettempdir(), "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}


_GIT = ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false"]


def safe_rel(path: str) -> str:
    """A repository-relative path with nothing that could leave the folder."""
    if (not isinstance(path, str) or not path or path.startswith(("/", "~")) or "\\" in path or "\x00" in path
            or re.match(r"^[A-Za-z]:", path) or ".." in Path(path).parts):
        raise FixError("A finding points outside the repository, so it was not patched.")
    return path


def safe_join(root: Path, rel: str) -> Path:
    """root / rel, refusing anything whose real location (through symlinks) is outside root."""
    p = root / safe_rel(rel)
    real_root = root.resolve()
    real = Path(os.path.realpath(p))
    if real != real_root and real_root not in real.parents:
        raise FixError("A path in this fix resolves outside the folder (a symbolic link), so nothing was touched.")
    return p


def is_code_edge(edge_id: str) -> bool:
    return isinstance(edge_id, str) and edge_id.startswith("code:")


def finding_ids(edge_ids: list[str]) -> list[str]:
    out = []
    for e in edge_ids:
        m = _FID.match(e)
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


STILL_RUNNING = ("The scan is still running. Results are shown as they arrive, but a fix is prepared from the "
                 "finished scan: propose it when the scan completes.")


def scan_running(ws: int) -> bool:
    newest = supa.select("jobs", {"ws": supa.eq(ws)}, columns="id,state", order="id.desc", limit=1)
    return bool(newest) and harness.effective_state(newest[0]) in harness.RUNNING


def latest_job(ws: int) -> dict | None:
    for r in supa.select("jobs", {"ws": supa.eq(ws)}, order="id.desc", limit=8):
        if r["state"] in SETTLED and isinstance(r.get("findings"), list) and r["findings"]:
            return r
    return None


def _source(job: dict) -> Path:
    src = harness.data_root() / str(job["id"]) / "repo"
    if not src.is_dir():
        raise FixError("This scan's working copy was cleared. Run the scan again to prepare a fix.")
    return src


def _original(job: dict, src: Path, path: str) -> str:
    safe_rel(path)
    try:
        # the scanned commit is the clone's root (depth 1); the fixes commit, if any, sits on top of it
        roots = harness._git(["rev-list", "--max-parents=0", "HEAD"], cwd=src).split()
        ref = roots[-1] if roots else "HEAD"
        return harness._git(["show", f"{ref}:{path}"], cwd=src)
    except RuntimeError:
        raise FixError(f"Could not read {path} from the scanned copy.") from None


def _diff(path: str, before: str, after: str) -> str:
    """A git-format patch for one file, made by git itself (so the missing-newline cases come out right)."""
    with tempfile.TemporaryDirectory() as d:
        for side, text in (("a", before), ("b", after)):
            p = safe_join(Path(d, side), path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8", newline="")
        # empty prefixes: the scratch layout (a/<path>, b/<path>) already is a normal git patch's a/ and b/
        r = _bytes_run(_GIT + ["diff", "--no-index", "--no-color", "--no-ext-diff", "--src-prefix=", "--dst-prefix=",
                               f"a/{path}", f"b/{path}"], cwd=d, env=_env())
    out = r.stdout
    if r.returncode not in (0, 1) or not out.strip():
        raise FixError(f"Could not build a patch for {path}.")
    return out


def _rule_counts(path: str, content: str) -> dict:
    out: dict[str, int] = {}
    for f in codescan.static_scan([{"path": path, "content": content}]):
        out[f["rule"]] = out.get(f["rule"], 0) + 1
    return out


def plan(ws: int, edge_ids: list[str]) -> dict:
    """The patch for the findings behind `edge_ids`. Raises FixError when there is nothing to build it from."""
    ids = finding_ids(edge_ids)
    if not ids:
        raise FixError("These steps are exposure, not weaknesses in code, so there is nothing to patch. "
                       "Pick the weakness steps (the fixes list does).")
    if scan_running(ws):
        raise FixError(STILL_RUNNING)
    job = latest_job(ws)
    if not job:
        raise FixError("No finished scan with findings in this workspace.")
    by_id = {f["id"]: f for f in job["findings"] if isinstance(f, dict) and "id" in f}
    chosen = [by_id[i] for i in ids if i in by_id]
    if not chosen:
        raise FixError("Those findings belong to an older scan. Run the scan again, then propose the fix.")
    src = _source(job)
    fixed, manual, files = [], [], []
    patch_parts = []
    for path in sorted({f["file"] for f in chosen}):
        before = _original(job, src, path)
        content = before
        # bottom-up, so earlier line numbers stay valid after each edit
        safe_rel(path)
        for f in sorted((x for x in chosen if x["file"] == path), key=lambda x: -x["line"]):
            res = fixers.try_fix(content, f)
            if not res:
                manual.append({"id": f["id"], "file": path, "line": f["line"], "rule": f["rule"], "title": f["title"],
                               "reason": "No automatic fix passed every safety check. This one needs a manual change."})
                continue
            content = res["content"]
            fixed.append({"id": f["id"], "file": path, "line": f["line"], "rule": f["rule"], "cwe": f.get("cwe", ""),
                          "title": f["title"], "method": res["method"], "explanation": res["explanation"],
                          "checks": res["checks"]})
        if content != before:
            part = _diff(path, before, content)
            patch_parts.append(part)
            files.append({"path": path, "before_sha": _sha(before), "after_sha": _sha(content),
                          "rules_before": _rule_counts(path, before), "rules_after": _rule_counts(path, content),
                          "fixed": [x for x in fixed if x["file"] == path],
                          "added": sum(1 for ln in part.splitlines() if ln.startswith("+") and not ln.startswith("+++")),
                          "removed": sum(1 for ln in part.splitlines() if ln.startswith("-") and not ln.startswith("---"))})
    patch = "".join(patch_parts)
    if not patch:
        raise FixError("None of the selected findings has an automatic fix that passed its safety checks. "
                       "Use Assistant → Fix to let the agent fix them (it is re-scanned and tested), or see the "
                       "findings for what to change by hand.")
    if len(patch) > MAX_PATCH:
        raise FixError("The patch is too large to review safely. Select fewer findings.")
    return {"job": job["id"], "repo": job["repo_url"], "patch": patch, "files": files, "fixed": fixed,
            "manual": manual, "finding_ids": [f["id"] for f in fixed]}


# ---- where the patch goes ----
def target(job_repo: str) -> tuple[str, Path | str]:
    """('local', folder) for a repository imported from a folder, else ('remote', 'owner/name')."""
    p = Path(job_repo) if job_repo.startswith(("/", "~")) or re.match(r"^[A-Za-z]:[\\/]", job_repo) else None
    if p is not None:
        if not (config.desktop_mode() or os.environ.get("APC_ALLOW_LOCAL") == "1"):
            raise FixError("Applying a fix to a local folder is only available in the desktop app.")
        if not (p.is_dir() and (p / ".git").exists()):
            raise FixError(f"The folder {p.name} is no longer available as a Git repository.")
        return "local", p
    return "remote", job_repo


def _bytes_run(cmd: list[str], data: str | None = None, **kw) -> subprocess.CompletedProcess:
    """Run git exchanging raw bytes: text mode would rewrite every \n as \r\n on Windows and corrupt patches."""
    r = subprocess.run(cmd, input=None if data is None else data.encode("utf-8"), capture_output=True, **kw)
    return subprocess.CompletedProcess(r.args, r.returncode, r.stdout.decode("utf-8", "replace"),
                                       r.stderr.decode("utf-8", "replace"))


def _git_apply(folder: Path, patch: str, *args: str) -> subprocess.CompletedProcess:
    return _bytes_run(_GIT + ["-C", str(folder), "apply", "--whitespace=nowarn", "-C1", *args, "-"], patch,
                      timeout=60, env=_env())


def _why(stderr: str, folder: Path) -> str:
    first = [ln for ln in stderr.splitlines() if ln.strip()][:2]
    return (" ".join(first).replace(str(folder), "") or "the patch does not apply")[:240]


def _sections(patch: str) -> list[str]:
    """The per-file parts of a multi-file git patch, in order."""
    parts = re.split(r"(?m)^(?=diff --git )", patch)
    return [p for p in parts if p]


def _section_path(section: str) -> str | None:
    """The file a patch part changes, from its `+++ b/<path>` line (None for a quoted or unusual header)."""
    m = re.search(r"(?m)^\+\+\+ b/(.+)$", section)
    return m.group(1).rstrip("\t") if m else None   # git ends a name that has spaces with a tab


def _uses_crlf(p: Path) -> bool:
    """True when every line break in the file is CRLF (a Windows checkout with core.autocrlf)."""
    try:
        data = p.read_bytes() if p.is_file() and not p.is_symlink() else b""
    except OSError:
        return False
    lf = data.count(b"\n")
    return lf > 0 and data.count(b"\r\n") == lf


def _to_crlf(section: str) -> str:
    """One file's patch with CRLF on its content lines, so it matches a CRLF working copy. Headers, hunk headers and
    the 'No newline at end of file' marker keep LF, and a line followed by that marker gets no CR (it has no break)."""
    lines = section.split("\n")
    out = []
    in_hunk = False
    for i, ln in enumerate(lines):
        if ln.startswith("@@"):
            in_hunk = True
        elif ln.startswith("diff --git "):
            in_hunk = False
        elif in_hunk and ln[:1] in (" ", "+", "-") and i + 1 < len(lines):
            nxt = lines[i + 1]
            if not nxt.startswith("\\") and not ln.endswith("\r"):
                ln += "\r"
        out.append(ln)
    return "\n".join(out)


def _for_folder(folder: Path, patch: str) -> str:
    """The patch with each file's part in that file's line endings. Fixes are computed from the scanned copy (LF),
    while a Windows checkout usually holds CRLF; git apply compares bytes, so an LF patch would never apply there.
    Files that are LF or mixed keep the patch as it is (git apply --check still has the last word)."""
    out = []
    for s in _sections(patch):
        rel = _section_path(s)
        try:
            crlf = rel is not None and _uses_crlf(safe_join(folder, rel))
        except FixError:
            crlf = False
        out.append(_to_crlf(s) if crlf else s)
    return "".join(out)


def apply_local(folder: Path, patch: str, reverse: bool = False) -> None:
    flag = ["-R"] if reverse else []
    patch = _for_folder(folder, patch)
    chk = _git_apply(folder, patch, "--check", *flag)
    if chk.returncode != 0:
        raise FixError(("The files changed since the scan, so Paladin did not touch them: " if not reverse else
                        "These files were edited after the fix, so it cannot be rolled back safely: ")
                       + _why(chk.stderr, folder) + ". Your work is untouched; scan again to refresh the fix.")
    done = _git_apply(folder, patch, *flag)
    if done.returncode != 0:                      # git apply is all-or-nothing, so nothing was written
        raise FixError("git could not apply the patch: " + _why(done.stderr, folder))


def uncommitted(folder: Path, paths: list[str]) -> list[str]:
    r = subprocess.run(_GIT + ["-C", str(folder), "status", "--porcelain", "--", *[safe_rel(p) for p in paths]],
                       capture_output=True, text=True, timeout=30, env=_env())
    return [ln[3:] for ln in r.stdout.splitlines() if ln.strip()]


def apply_to_contents(current: dict[str, str | None], files: list[dict], patch: str) -> dict[str, str]:
    """The patch applied to the CURRENT content of each file (a scratch folder), so a change made upstream since the
    scan is kept, or the apply is refused. `current[path]` is None when the file no longer exists."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        subprocess.run(_GIT + ["init", "-q"], cwd=root, check=True, capture_output=True, env=_env())
        for f in files:
            text = current.get(f["path"])
            if text is None:
                raise FixError(f"{f['path']} no longer exists in the repository, so this fix cannot be applied. "
                               "Scan again to refresh it.")
            p = safe_join(root, f["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8", newline="")
        r = _git_apply(root, patch)
        if r.returncode != 0:
            raise FixError("The repository changed since the scan, so the fix no longer applies: " + _why(r.stderr, root)
                           + ". Nothing was sent; scan again to refresh the fix.")
        return {f["path"]: safe_join(root, f["path"]).read_text(encoding="utf-8") for f in files}


def verify_files(read, files: list[dict]) -> dict:
    """`read(path) -> str | None`. Checks the files as they are now against what the fix was meant to produce."""
    problems, notes = [], []
    for f in files:
        text = read(f["path"])
        if text is None:
            problems.append(f"{f['path']}: file is missing")
            continue
        if f["path"].endswith(".py"):
            try:
                compile(text, f["path"], "exec")      # parse only, never executed
            except (SyntaxError, ValueError) as e:
                problems.append(f"{f['path']}: does not parse ({e.__class__.__name__})")
                continue
        now = _rule_counts(f["path"], text)
        for rule, n in now.items():
            if n > f["rules_after"].get(rule, 0):
                problems.append(f"{f['path']}: {rule} still matches {n} time(s), the fix left {f['rules_after'].get(rule, 0)}")
        if _sha(text) != f["after_sha"]:
            notes.append(f"{f['path']} was edited after the fix; its current content was checked")
    return {"ok": not problems, "problems": problems, "notes": notes}


def summary_runbook(p: dict) -> str:
    lines = [f"Patch for {len(p['fixed'])} finding(s) in {len(p['files'])} file(s). Review the diff, then approve."]
    for f in p["fixed"]:
        lines.append(f"- {f['file']}:{f['line']} {f['title']} ({f['cwe']}): {f['explanation']}")
    for m in p["manual"]:
        lines.append(f"- {m['file']}:{m['line']} {m['title']}: needs a manual change. {m['reason']}")
    lines.append("Checks per fix: the file still parses, the rule stops matching, nothing new is introduced. "
                 "Tests are not run; repository code is never executed.")
    return "\n".join(lines)


def dumps(files: list[dict]) -> str:
    return json.dumps(files)
