from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

import asyncio

from . import ai, auth, codefix, github_access, remediation as rem

router = APIRouter(prefix="/api/remediations", tags=["remediation"])


class Propose(BaseModel):
    edges: list[str] = Field(min_length=1, max_length=50)
    title: str = Field(default="Proposed fix", max_length=120)


def can_approve(user: dict) -> bool:
    """Hook for roles (owned by the auth work). Today any signed-in workspace owner may approve."""
    return True


def _guard(fn, *a):
    try:
        return fn(*a)
    except KeyError:
        raise HTTPException(404, "remediation not found")
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.get("")
def list_all(u: dict = Depends(auth.require_user)):
    return {"remediations": rem.list_(u["id"]), "ai_enabled": ai.enabled()}


@router.post("")
def propose(b: Propose, u: dict = Depends(auth.require_user)):
    try:
        return rem.propose(u["id"], u["actor"], b.edges, b.title)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/{rid}")
def detail(rid: int, u: dict = Depends(auth.require_user)):
    r = _guard(rem.get, u["id"], rid)
    r["audit"] = rem.audit_log(u["id"], rid)
    return r


@router.get("/{rid}/patch", response_class=PlainTextResponse)
def patch(rid: int, u: dict = Depends(auth.require_user)):
    r = _guard(rem.get, u["id"], rid)
    if r["kind"] != "code" or not r["patch"]:
        raise HTTPException(404, "this remediation has no patch")
    return r["patch"]


@router.post("/{rid}/approve")
def approve(rid: int, u: dict = Depends(auth.require_user)):
    if not can_approve(u):
        raise HTTPException(403, "approver role required")
    return _guard(rem.approve, u["id"], rid, u["actor"])


@router.post("/{rid}/execute")
async def execute(rid: int, u: dict = Depends(auth.require_user)):
    ws = u["id"]
    cur = await asyncio.to_thread(_guard, rem.get, ws, rid)
    if cur["kind"] != "code":
        return await asyncio.to_thread(_guard, rem.execute, ws, rid, u["actor"])
    if cur["state"] != "approved":
        raise HTTPException(409, f"cannot go from {cur['state']} to executed")
    try:
        repo = await asyncio.to_thread(rem._job_repo, ws, cur)
        kind, where = codefix.target(repo)
        if kind == "local":
            dirty = await asyncio.to_thread(codefix.uncommitted, where, [f["path"] for f in cur["files"]])
            await asyncio.to_thread(codefix.apply_local, where, cur["patch"])      # check, then apply; all or nothing
            applied = f"local folder {where.name}" + (f" ({len(dirty)} file(s) had your uncommitted edits, kept)" if dirty else "")
        else:
            final = await asyncio.to_thread(codefix.materialize, cur["job"], repo, cur["files"], cur["patch"])
            url = await github_access.open_fix_pr(
                u, repo, cur["title"] or "Security fixes", cur["runbook"],
                f"Fix {len(cur['finding_ids'])} security finding(s) found by Paladin", final)
            applied = url
    except codefix.FixError as e:
        raise HTTPException(409, str(e)) from None
    return await asyncio.to_thread(_guard, rem.execute, ws, rid, u["actor"], applied)


@router.post("/{rid}/verify")
def verify(rid: int, u: dict = Depends(auth.require_user)):
    return _guard(rem.verify, u["id"], rid, u["actor"])


@router.post("/{rid}/rollback")
def rollback(rid: int, u: dict = Depends(auth.require_user)):
    return _guard(rem.rollback, u["id"], rid, u["actor"])
