from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

import asyncio
import re

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
        raise HTTPException(404, "remediation not found") from None
    except ValueError as e:
        raise HTTPException(409, str(e)) from None


@router.get("")
def list_all(u: dict = Depends(auth.require_user)):
    return {"remediations": rem.list_(u["id"]), "ai_enabled": ai.enabled()}


@router.post("")
def propose(b: Propose, u: dict = Depends(auth.require_user)):
    try:
        return rem.propose(u["id"], u["actor"], b.edges, b.title)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


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


_locks: dict[int, asyncio.Lock] = {}


def _lock(rid: int) -> asyncio.Lock:
    return _locks.setdefault(rid, asyncio.Lock())


@router.post("/{rid}/execute")
async def execute(rid: int, u: dict = Depends(auth.require_user)):
    ws = u["id"]
    async with _lock(rid):            # a second click waits, then sees the state the first one left behind
        cur = await asyncio.to_thread(_guard, rem.get, ws, rid)
        if cur["kind"] != "code":
            return await asyncio.to_thread(_guard, rem.execute, ws, rid, u["actor"])
        if cur["state"] != "approved":
            raise HTTPException(409, f"cannot go from {cur['state']} to executed")
        local_applied = None
        try:
            repo = await asyncio.to_thread(rem._job_repo, ws, cur)
            kind, where = codefix.target(repo)
            if kind == "local":
                dirty = await asyncio.to_thread(codefix.uncommitted, where, [f["path"] for f in cur["files"]])
                await asyncio.to_thread(codefix.apply_local, where, cur["patch"])      # check, then apply; all or nothing
                local_applied = where
                applied = f"local folder {where.name}" + (
                    f" ({len(dirty)} file(s) had your uncommitted edits, kept)" if dirty else "")
            else:
                paths = [f["path"] for f in cur["files"]]
                current = await github_access.read_repo_files(u, repo, paths)
                # applied to what the default branch holds NOW: upstream changes are kept, or the fix is refused
                final = await asyncio.to_thread(codefix.apply_to_contents, current, cur["files"], cur["patch"])
                applied = await github_access.open_fix_pr(
                    u, repo, cur["title"] or "Security fixes", cur["runbook"],
                    f"Fix {len(cur['finding_ids'])} security finding(s) found by Paladin", final)
        except codefix.FixError as e:
            raise HTTPException(409, str(e)) from None
        try:
            return await asyncio.to_thread(_guard, rem.execute, ws, rid, u["actor"], applied)
        except HTTPException:
            if local_applied is not None:   # the files changed but the record did not: undo, so state and disk agree
                try:
                    await asyncio.to_thread(codefix.apply_local, local_applied, cur["patch"], True)
                except codefix.FixError:
                    pass
            raise


@router.post("/{rid}/verify")
async def verify(rid: int, u: dict = Depends(auth.require_user)):
    ws = u["id"]
    async with _lock(rid):
        cur = await asyncio.to_thread(_guard, rem.get, ws, rid)
        if cur["kind"] == "code" and cur["state"] == "executed" and re.match(r"^https://", cur.get("applied") or ""):
            m = re.search(r"/pull/(\d+)$", cur["applied"])
            repo = await asyncio.to_thread(rem._job_repo, ws, cur)
            if not m or not await github_access.pull_merged(u, repo, int(m.group(1))):
                raise HTTPException(409, "The pull request is not merged yet. Merge it on GitHub, then verify again. "
                                         "Nothing is marked fixed until the change is in the repository.")
            contents = await github_access.read_repo_files(u, repo, [f["path"] for f in cur["files"]])
            return await asyncio.to_thread(_guard, rem.verify_remote, ws, rid, u["actor"], contents)
        return await asyncio.to_thread(_guard, rem.verify, ws, rid, u["actor"])


@router.post("/{rid}/rollback")
def rollback(rid: int, u: dict = Depends(auth.require_user)):
    return _guard(rem.rollback, u["id"], rid, u["actor"])
