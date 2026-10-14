"""HTTP surface for workspaces, repository onboarding (resolve, suggest, import), GitHub status and preferences."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import auth, github, harness, prefs, workspaces

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
        workspaces.open_(uid, existing["id"])
        jobs = harness.list_jobs(existing["id"])
        try:
            # reuse the latest scan unless there is none or it failed (the user is probably retrying after a fix)
            if jobs and jobs[0].get("state") != "failed":
                job = harness.get(existing["id"], jobs[0]["id"])
            else:
                job = harness.start(existing["id"], existing["repo_url"])
        except (ValueError, RuntimeError) as e:
            raise HTTPException(409, str(e)) from None
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
