import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from . import auth, github_access, harness

router = APIRouter(prefix="/api/harness", tags=["harness"])


class StartBody(BaseModel):
    repo_url: str = Field(max_length=300)


@router.get("/config")
def cfg(u: dict = Depends(auth.require_user)):
    return harness.config()


@router.get("/jobs")
def jobs(u: dict = Depends(auth.require_user)):
    return {"jobs": harness.list_jobs(u["id"])}


async def start_scan(u: dict, url: str) -> dict:
    """Start a scan with the right clone credential: on the web a read-only token for this one repo, and only if it
    is in the signed-in user's own GitHub App installation; otherwise none (public repos only)."""
    token = None
    if not auth.desktop_mode():
        m = harness.URL_RE.match(url.strip())
        if m:
            token = await github_access.clone_token(u["user_id"], m[1], m[2])
    if token is None:
        return await asyncio.to_thread(harness.start, u["id"], url)
    return await asyncio.to_thread(lambda: harness.start(u["id"], url, token=token))


@router.post("/jobs")
async def start(b: StartBody, u: dict = Depends(auth.require_user)):
    try:
        return await start_scan(u, b.repo_url)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from None


def _get(ws: int, jid: int) -> dict:
    try:
        return harness.get(ws, jid)
    except KeyError:
        raise HTTPException(404, "job not found") from None


@router.get("/jobs/{jid}")
def job(jid: int, u: dict = Depends(auth.require_user)):
    return _get(u["id"], jid)


@router.get("/jobs/{jid}/patch", response_class=PlainTextResponse)
def patch(jid: int, u: dict = Depends(auth.require_user)):
    return _get(u["id"], jid)["diff"]


@router.get("/jobs/{jid}/file")
def patched_file(jid: int, path: str, u: dict = Depends(auth.require_user)):
    _get(u["id"], jid)
    try:
        return harness.patched_file(u["id"], jid, path)
    except (KeyError, OSError, UnicodeDecodeError):
        raise HTTPException(404, "file not found among this job's changes") from None


@router.post("/jobs/{jid}/pr")
async def pr(jid: int, u: dict = Depends(auth.require_user)):
    """Commits the job's fixes to the repo's `fixes` branch (fast-forward only) and opens or reuses one PR.
    Web: only for repos in the user's own GitHub App installation. Desktop: with the user's own token."""
    return await github_access.open_job_pr(u, jid)
