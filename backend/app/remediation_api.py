from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import ai, auth, remediation as rem

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
        return rem.propose(u["id"], u["email"], b.edges, b.title)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/{rid}")
def detail(rid: int, u: dict = Depends(auth.require_user)):
    r = _guard(rem.get, u["id"], rid)
    r["audit"] = rem.audit_log(u["id"], rid)
    return r


@router.post("/{rid}/approve")
def approve(rid: int, u: dict = Depends(auth.require_user)):
    if not can_approve(u):
        raise HTTPException(403, "approver role required")
    return _guard(rem.approve, u["id"], rid, u["email"])


@router.post("/{rid}/execute")
def execute(rid: int, u: dict = Depends(auth.require_user)):
    return _guard(rem.execute, u["id"], rid, u["email"])


@router.post("/{rid}/verify")
def verify(rid: int, u: dict = Depends(auth.require_user)):
    return _guard(rem.verify, u["id"], rid, u["email"])


@router.post("/{rid}/rollback")
def rollback(rid: int, u: dict = Depends(auth.require_user)):
    return _guard(rem.rollback, u["id"], rid, u["email"])
