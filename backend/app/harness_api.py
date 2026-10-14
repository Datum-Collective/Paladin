from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from . import auth, harness

router = APIRouter(prefix="/api/harness", tags=["harness"])


class StartBody(BaseModel):
    repo_url: str = Field(max_length=300)


@router.get("/config")
def cfg(u: dict = Depends(auth.require_user)):
    return harness.config()


@router.get("/jobs")
def jobs(u: dict = Depends(auth.require_user)):
    return {"jobs": harness.list_jobs(u["id"])}


@router.post("/jobs")
def start(b: StartBody, u: dict = Depends(auth.require_user)):
    try:
        return harness.start(u["id"], b.repo_url)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))


def _get(ws: int, jid: int) -> dict:
    try:
        return harness.get(ws, jid)
    except KeyError:
        raise HTTPException(404, "job not found")


@router.get("/jobs/{jid}")
def job(jid: int, u: dict = Depends(auth.require_user)):
    return _get(u["id"], jid)


@router.get("/jobs/{jid}/patch", response_class=PlainTextResponse)
def patch(jid: int, u: dict = Depends(auth.require_user)):
    return _get(u["id"], jid)["diff"]


@router.post("/jobs/{jid}/pr")
def pr(jid: int, u: dict = Depends(auth.require_user)):
    _get(u["id"], jid)
    try:
        return harness.open_pr(u["id"], jid)
    except PermissionError as e:
        raise HTTPException(409, str(e))
    except RuntimeError as e:
        raise HTTPException(502 if "GitHub" in str(e) or "git " in str(e) else 409, str(e)[:200])
