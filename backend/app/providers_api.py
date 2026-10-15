"""HTTP surface for AI providers: list, models, validate, key push (desktop only) and the streaming assistant."""
import asyncio
import json
import os
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import assistant, auth, keys
from .providers import ProviderError, all_providers, get_provider

router = APIRouter()
STATUS_FOR = {"auth": 401, "quota": 402, "permission": 403, "not_found": 404, "too_large": 413,
              "rate_limit": 429, "overloaded": 503, "server": 502, "network": 502, "invalid": 400}
EFFORTS = ("low", "medium", "high")


class KeyPush(BaseModel):
    anthropic: str | None = Field(default=None, max_length=512)
    openai: str | None = Field(default=None, max_length=512)
    github: str | None = Field(default=None, max_length=512)


class Msg(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=assistant.MAX_CONTENT)


class ChatBody(BaseModel):
    provider: str = Field(max_length=32)
    model: str = Field(min_length=1, max_length=128)
    messages: list[Msg] = Field(min_length=1, max_length=assistant.MAX_MESSAGES)
    effort: str | None = Field(default=None, max_length=16)
    include_context: bool = True


def _provider(pid: str):
    try:
        return get_provider(pid)
    except KeyError:
        raise HTTPException(404, "unknown provider") from None


@router.get("/api/providers")
def list_providers(_: dict = Depends(auth.require_user)):
    st = keys.status()
    return {"providers": [{"id": p.id, "name": p.name, "configured": st[p.id]} for p in all_providers()],
            "github": st["github"]}


@router.put("/api/providers/keys")
def push_keys(body: KeyPush, request: Request):
    """Only the Electron main process may set keys: it proves itself with the per-launch token. Write-only."""
    if not auth.desktop_mode():
        raise HTTPException(404, "not available")
    expected = os.environ.get("APC_DESKTOP_TOKEN", "")
    given = request.headers.get("x-desktop-token", "")
    if not expected or not secrets.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(403, "desktop token required")
    try:
        keys.set_many({k: v for k, v in body.model_dump(exclude_unset=True).items()})
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return keys.status()


@router.get("/api/providers/{pid}/models")
async def models(pid: str, _: dict = Depends(auth.require_user)):
    p = _provider(pid)
    try:
        return {"models": await p.list_models()}
    except ProviderError as e:
        raise HTTPException(STATUS_FOR.get(e.kind, 502), f"{e.message} {e.to_event()['hint']}".strip()) from None


@router.post("/api/providers/{pid}/validate")
async def validate(pid: str, _: dict = Depends(auth.require_user)):
    return await _provider(pid).validate()


class TestBody(BaseModel):
    model: str = Field(min_length=1, max_length=128)


@router.post("/api/providers/{pid}/test")
async def test_connection(pid: str, b: TestBody, _: dict = Depends(auth.require_user)):
    """Setup's connection test: a real one-token round trip. Failures are a normal 200 {ok: false} so the UI can
    show the provider's reason beside the field instead of a generic request error."""
    try:
        return await _provider(pid).probe(b.model)
    except HTTPException:
        raise
    except Exception:  # a malformed provider reply must reach the UI as a reason, not a bare 500
        return {"ok": False, "error": ProviderError("server", "The provider sent a reply Paladin could not read.").to_event()}


@router.post("/api/assistant/chat")
async def chat(b: ChatBody, request: Request, u: dict = Depends(auth.require_user)):
    p = _provider(b.provider)
    if b.messages[0].role != "user" or b.messages[-1].role != "user":
        raise HTTPException(422, "conversation must start and end with a user message")
    if sum(len(m.content) for m in b.messages) > assistant.MAX_TOTAL:
        raise HTTPException(413, "conversation too long")
    effort = b.effort if b.effort in EFFORTS else None
    system = await asyncio.to_thread(assistant.system_prompt, u["id"], b.include_context)  # SQLite + graph work
    msgs = assistant.clean_messages([m.model_dump() for m in b.messages])

    async def gen():
        try:
            async for ev in p.stream(model=b.model, system=system, messages=msgs, effort=effort):
                if await request.is_disconnected():
                    return  # closing the generator closes the upstream connection
                yield f"data: {json.dumps(ev)}\n\n"
        except Exception:  # never leak a stack trace or a key into the stream
            yield f"data: {json.dumps(ProviderError('server', 'The assistant failed unexpectedly.').to_event())}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
