"""HTTP surface for workspaces, repository onboarding (resolve, suggest, import), GitHub status and preferences."""
import os
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import auth, github, harness, prefs, remediation, store, workspaces

router = APIRouter()
GH_STATUS = {"not_found": 404, "auth": 424, "rate_limit": 429, "network": 502, "server": 502, "invalid": 422}


class CreateBody(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    repo_url: str | None = Field(default=None, max_length=300)


class RenameBody(BaseModel):
    name: str = Field(max_length=200)


class QueryBody(BaseModel):
    query: str = Field(max_length=400)


def _ws(fn, *a):
    try:
        return fn(*a)
    except workspaces.WorkspaceError as e:
        raise HTTPException(e.status, e.message) from None


def _gh_error(e: github.GitHubError) -> HTTPException:
    return HTTPException(GH_STATUS.get(e.kind, 502), e.message)


@router.get("/api/workspaces")
def list_workspaces(u: dict = Depends(auth.require_user)):
    return workspaces.listing(u["user_id"])


@router.post("/api/workspaces")
def create_workspace(b: CreateBody, u: dict = Depends(auth.require_user)):
    ws = _ws(workspaces.create, u["user_id"], b.name, b.repo_url)
    return {"workspace": ws, **workspaces.listing(u["user_id"])}


@router.post("/api/workspaces/import")
async def import_repo(b: QueryBody, u: dict = Depends(auth.require_user)):
    """One step from a pasted link to a scanning workspace. A failure leaves no half-made workspace behind."""
    parsed = github.parse(b.query)
    if not parsed:
        raise HTTPException(422, "Enter a GitHub repository link or owner/name.")
    uid = u["user_id"]
    existing = workspaces.find_by_repo(uid, github.canonical(*parsed))
    if existing:
        jobs = harness.list_jobs(existing["id"])
        try:
            # reuse the latest scan unless there is none or it failed (the user is probably retrying after a fix)
            if jobs and jobs[0].get("state") != "failed":
                job = harness.get(existing["id"], jobs[0]["id"])
            else:
                job = harness.start(existing["id"], existing["repo_url"])
        except (ValueError, RuntimeError) as e:
            raise HTTPException(409, str(e)) from None
        workspaces.open_(uid, existing["id"])      # switch only once the scan is known to be running
        return {"workspace": workspaces._row(existing), "job": job, "reopened": True, **workspaces.listing(uid)}
    try:
        info = await github.repo(*parsed)
    except github.GitHubError as e:
        raise _gh_error(e) from None
    previous = workspaces.active(uid)
    ws = _ws(workspaces.create_for_repo, uid, info["full_name"], github.canonical(*info["full_name"].split("/", 1)))
    try:
        job = harness.start(ws["id"], ws["repo_url"])
    except (ValueError, RuntimeError) as e:
        try:               # best effort: never let cleanup mask the real error
            workspaces.delete(uid, ws["id"])
            workspaces.open_(uid, previous)
        except Exception:
            pass
        raise HTTPException(409 if isinstance(e, RuntimeError) else 422, str(e)) from None
    return {"workspace": ws, "job": job, "reopened": False, **workspaces.listing(uid)}


@router.post("/api/workspaces/{ws}/open")
def open_workspace(ws: int, u: dict = Depends(auth.require_user)):
    return _ws(workspaces.open_, u["user_id"], ws)


@router.patch("/api/workspaces/{ws}")
def rename_workspace(ws: int, b: RenameBody, u: dict = Depends(auth.require_user)):
    return {"workspace": _ws(workspaces.rename, u["user_id"], ws, b.name)}


@router.delete("/api/workspaces/{ws}")
def delete_workspace(ws: int, u: dict = Depends(auth.require_user)):
    return _ws(workspaces.delete, u["user_id"], ws)


@router.post("/api/repos/resolve")
async def resolve(b: QueryBody, u: dict = Depends(auth.require_user)):
    parsed = github.parse(b.query)
    if not parsed:
        raise HTTPException(422, "Enter a GitHub repository link or owner/name.")
    try:
        info = await github.repo(*parsed)
    except github.GitHubError as e:
        raise _gh_error(e) from None
    owner, name = info["full_name"].split("/", 1)
    existing = workspaces.find_by_repo(u["user_id"], github.canonical(owner, name))
    return {"owner": owner, "repo": name, "full_name": info["full_name"], "private": info["private"],
            "default_branch": info["default_branch"], "description": info["description"], "url": info["url"],
            "workspace_id": existing["id"] if existing else None}


@router.get("/api/repos/suggest")
async def suggest(q: str = "", u: dict = Depends(auth.require_user)):
    q = q.strip()[:200]
    low = q.lower()
    out: list[dict] = []
    parsed = github.parse(q)
    if parsed:
        out.append({"kind": "url", "title": f"Open {parsed[0]}/{parsed[1]}", "subtitle": "github.com",
                    "url": github.canonical(*parsed)})
    have = set()
    for w in workspaces.listing(u["user_id"])["workspaces"]:
        hay = f"{w['name']} {w['repo_url'] or ''}".lower()
        if not low or low in hay:
            out.append({"kind": "workspace", "title": w["name"], "subtitle": w["repo_url"] or f"{w['events']} events",
                        "workspace_id": w["id"]})
        if w["repo_url"]:
            have.add(w["repo_url"].lower())
    err = None
    try:
        for r in await github.user_repos():
            if r["url"].lower() in have:
                continue
            if not low or low in f"{r['full_name']} {r['description'] or ''}".lower():
                out.append({"kind": "github", "title": r["full_name"], "subtitle": r["description"] or ("Private" if r["private"] else "Public"),
                            "url": r["url"], "private": r["private"]})
    except github.GitHubError as e:
        err = e.message
    # cap per kind so a long repo list never buries the typed link or the workspaces
    seen: dict[str, int] = {}
    items = []
    for i in out:
        seen[i["kind"]] = seen.get(i["kind"], 0) + 1
        if seen[i["kind"]] <= (6 if i["kind"] != "url" else 1):
            items.append(i)
    return {"suggestions": items, "github_error": err}


@router.get("/api/github/status")
async def github_status(_: dict = Depends(auth.require_user)):
    return await github.whoami()


@router.get("/api/prefs")
def get_prefs(u: dict = Depends(auth.require_user)):
    return prefs.get(u["user_id"])


@router.put("/api/prefs")
def put_prefs(body: dict, u: dict = Depends(auth.require_user)):
    try:
        return prefs.patch(u["user_id"], body)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


# ---- local folders (desktop only) ----
class PathBody(BaseModel):
    path: str = Field(max_length=1000)


def _local(path: str) -> Path:
    if not auth.desktop_mode():
        raise HTTPException(404, "Local folders are only available in the desktop app.")
    p = os.path.expanduser((path or "").strip())
    if not p:
        raise HTTPException(422, "Choose a folder path.")
    if not os.path.isabs(p):
        raise HTTPException(422, "Use an absolute path.")
    d = Path(p).expanduser()
    if not d.is_dir():
        raise HTTPException(422, "That folder does not exist or is not readable.")
    d = d.resolve()
    if not (d / ".git").exists():
        raise HTTPException(422, "This folder is not a Git repository. Paladin scans committed code, so run `git init` "
                                 "and commit first.")
    return d


@router.post("/api/repos/resolve-local")
def resolve_local(b: PathBody, u: dict = Depends(auth.require_user)):
    d = _local(b.path)
    existing = workspaces.find_by_repo(u["user_id"], str(d))
    return {"name": d.name, "path": str(d), "is_git": True, "workspace_id": existing["id"] if existing else None}


@router.post("/api/workspaces/import-local")
def import_local(b: PathBody, u: dict = Depends(auth.require_user)):
    d = _local(b.path)
    uid = u["user_id"]
    existing = workspaces.find_by_repo(uid, str(d))
    if existing:
        try:
            job = harness.start(existing["id"], str(d))
        except (ValueError, RuntimeError) as e:
            raise HTTPException(409, str(e)) from None
        workspaces.open_(uid, existing["id"])
        return {"workspace": workspaces._row(existing), "job": job, "reopened": True, **workspaces.listing(uid)}
    previous = workspaces.active(uid)
    ws = _ws(workspaces.create_for_repo, uid, d.name, str(d))
    try:
        job = harness.start(ws["id"], str(d))
    except (ValueError, RuntimeError) as e:
        try:
            workspaces.delete(uid, ws["id"])
            workspaces.open_(uid, previous)
        except Exception:
            pass
        raise HTTPException(409 if isinstance(e, RuntimeError) else 422, str(e)) from None
    return {"workspace": ws, "job": job, "reopened": False, **workspaces.listing(uid)}


# ---- activity ----
@router.get("/api/activity")
def activity(limit: int = 100, u: dict = Depends(auth.require_user)):
    """Scan history and remediation steps for the open workspace, newest first. Everything here is recorded
    elsewhere (jobs, audit); this only merges it."""
    ws, limit = u["id"], max(1, min(limit, 300))
    harness.ensure()
    items = []
    for r in store.q("SELECT id,repo_url,state,error,updated FROM jobs WHERE ws=? ORDER BY id DESC LIMIT ?", (ws, limit)):
        items.append({"kind": "scan", "id": r["id"], "title": f"Scan {r['repo_url']}", "state": r["state"],
                      "detail": r["error"] or "", "ts": r["updated"],
                      "retry": r["repo_url"] if r["state"] == "failed" else None,
                      "cancel": r["state"] in harness.RUNNING})
    for r in remediation.history(ws, limit):
        items.append({"kind": "remediation", "id": r["id"], "title": r["title"] or "Remediation", "action": r["action"],
                      "actor": r["actor"], "detail": r["detail"], "state": r["state"], "ts": r["ts"]})
    items.sort(key=lambda i: i["ts"], reverse=True)
    return {"items": items[:limit]}


# ---- storage ----
def _tree_bytes(p: Path) -> int:
    total = 0
    for f in p.rglob("*"):
        try:
            if f.is_file() and not f.is_symlink():
                total += f.stat().st_size
        except OSError:
            pass
    return total


@router.get("/api/storage")
def storage(u: dict = Depends(auth.require_user)):
    harness.ensure()
    db = store.db_path()
    db_bytes = sum(p.stat().st_size for p in (db, Path(f"{db}-wal"), Path(f"{db}-shm")) if p.exists())
    mine = [r["id"] for r in store.q("SELECT j.id FROM jobs j JOIN workspaces w ON w.id=j.ws WHERE w.owner=?", (u["user_id"],))]
    dirs = [harness.data_root() / str(j) for j in mine if (harness.data_root() / str(j)).exists()]
    return {"database_bytes": db_bytes,
            "clones": {"count": len(dirs), "bytes": sum(_tree_bytes(d) for d in dirs)}}


@router.delete("/api/storage/clones")
def clear_clones(u: dict = Depends(auth.require_user)):
    """Delete cloned working copies of settled scans (done, failed, PR opened). Scans in progress and scans with
    fixes awaiting approval are kept; findings and history always stay."""
    harness.ensure()
    # 'ready' jobs still hold the fix branch awaiting approval, so only settled scans are cleared
    rows = store.q("SELECT j.id FROM jobs j JOIN workspaces w ON w.id=j.ws "
                   "WHERE w.owner=? AND j.state IN ('done','failed','cancelled','pr_opened')", (u["user_id"],))
    removed = 0
    for r in rows:
        d = harness.data_root() / str(r["id"])
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
    return {"removed": removed, "at": time.time()}
