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
    ref = "HEAD~1" if job["state"] in ("ready", "pr_opened") and job.get("branch") else "HEAD"
    try:
        return harness._git(["show", f"{ref}:{path}"], cwd=src)
    except RuntimeError:
        raise FixError(f"Could not read {path} from the scanned copy.") from None


def _diff(path: str, before: str, after: str) -> str:
    """A git-format patch for one file, made by git itself (so the missing-newline cases come out right)."""
    with tempfile.TemporaryDirectory() as d:
        for side, text in (("a", before), ("b", after)):
            p = Path(d, side, path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8", newline="")
        r = subprocess.run(["git", "diff", "--no-index", "--no-color", "--no-ext-diff", f"a/{path}", f"b/{path}"],
                           cwd=d, capture_output=True, text=True, env={"PATH": os.environ.get("PATH", ""), "HOME": d})
    out = r.stdout
    if r.returncode not in (0, 1) or not out.strip():
        raise FixError(f"Could not build a patch for {path}.")
    # the scratch layout (a/<path>, b/<path>) doubled the prefixes; a normal git patch has a/<path> and b/<path>
    out = re.sub(r"^(diff --git |--- |\+\+\+ )(?:a/)?a/", r"\1a/", out, flags=re.M)
    out = re.sub(r"^(diff --git a/\S+ |\+\+\+ )b/b/", r"\1b/", out, flags=re.M)
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
                       "See the findings for what to change by hand.")
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


def _git_apply(folder: Path, patch: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(folder), "-c", "core.hooksPath=/dev/null", "apply", "--whitespace=nowarn", "-C1", *args, "-"],
                          input=patch, capture_output=True, text=True, timeout=60,
                          env={"PATH": os.environ.get("PATH", ""), "HOME": str(folder)})


def _why(stderr: str, folder: Path) -> str:
    first = [ln for ln in stderr.splitlines() if ln.strip()][:2]
    return (" ".join(first).replace(str(folder), "") or "the patch does not apply")[:240]


def apply_local(folder: Path, patch: str, reverse: bool = False) -> None:
    flag = ["-R"] if reverse else []
    chk = _git_apply(folder, patch, "--check", *flag)
    if chk.returncode != 0:
        raise FixError(("The files changed since the scan, so Paladin did not touch them: " if not reverse else
                        "These files were edited after the fix, so it cannot be rolled back safely: ")
                       + _why(chk.stderr, folder) + ". Your work is untouched; scan again to refresh the fix.")
    done = _git_apply(folder, patch, *flag)
    if done.returncode != 0:                      # git apply is all-or-nothing, so nothing was written
        raise FixError("git could not apply the patch: " + _why(done.stderr, folder))


def uncommitted(folder: Path, paths: list[str]) -> list[str]:
    r = subprocess.run(["git", "-C", str(folder), "status", "--porcelain", "--", *paths], capture_output=True,
                       text=True, timeout=30, env={"PATH": os.environ.get("PATH", ""), "HOME": str(folder)})
    return [ln[3:] for ln in r.stdout.splitlines() if ln.strip()]


def materialize(job_id: int, job_repo: str, files: list[dict], patch: str) -> dict[str, str]:
    """Final content of each patched file: the scanned original with the stored patch applied in a scratch folder."""
    job = supa.first("jobs", {"id": supa.eq(job_id)})
    if not job:
        raise FixError("The scan this fix came from no longer exists.")
    src = _source(job)
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
        for f in files:
            p = root / f["path"]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(_original(job, src, f["path"]), encoding="utf-8", newline="")
        r = _git_apply(root, patch)
        if r.returncode != 0:
            raise FixError("The stored patch no longer applies to the scanned files: " + _why(r.stderr, root))
        return {f["path"]: (root / f["path"]).read_text(encoding="utf-8") for f in files}


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
