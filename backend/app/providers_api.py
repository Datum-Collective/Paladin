"""HTTP surface for AI providers: list, models, validate, key push (desktop only) and the streaming assistant."""
import asyncio
import json
import os
import secrets
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import assistant, auth, conversations, keys, supa
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
    # with a conversation, history comes from storage and only the last message (the new question) is used
    conversation_id: int | None = Field(default=None, ge=1)
    client_id: str | None = Field(default=None, min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    retry: bool = False      # answer the stored question again (after a failed reply) without storing it twice


class ConvBody(BaseModel):
    title: str = Field(default="", max_length=200)


FLUSH_S = 0.8      # how often a streaming reply is written through, so a crash loses at most this much


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


@router.get("/api/conversations")
def list_conversations(u: dict = Depends(auth.require_user)):
    return {"conversations": conversations.list_for(u["id"])}


@router.post("/api/conversations")
def create_conversation(b: ConvBody, u: dict = Depends(auth.require_user)):
    return conversations.create(u["id"], b.title)


def _conv(fn, *args):
    try:
        return fn(*args)
    except conversations.NotFound:
        raise HTTPException(404, "conversation not found") from None


@router.patch("/api/conversations/{cid}")
def rename_conversation(cid: int, b: ConvBody, u: dict = Depends(auth.require_user)):
    return _conv(conversations.rename, u["id"], cid, b.title)


@router.delete("/api/conversations/{cid}")
def delete_conversation(cid: int, u: dict = Depends(auth.require_user)):
    _conv(conversations.delete, u["id"], cid)
    return {"ok": True}


@router.get("/api/conversations/{cid}/messages")
def conversation_messages(cid: int, u: dict = Depends(auth.require_user)):
    return {"conversation": _conv(conversations.get, u["id"], cid), "messages": _conv(conversations.messages, u["id"], cid)}


@router.post("/api/assistant/chat")
async def chat(b: ChatBody, request: Request, u: dict = Depends(auth.require_user)):
    p = _provider(b.provider)
    if b.messages[0].role != "user" or b.messages[-1].role != "user":
        raise HTTPException(422, "conversation must start and end with a user message")
    if sum(len(m.content) for m in b.messages) > assistant.MAX_TOTAL:
        raise HTTPException(413, "conversation too long")
    effort = b.effort if b.effort in EFFORTS else None
    ws, cid = u["id"], b.conversation_id
    saved = {}
    if cid is not None:
        question = b.messages[-1].content
        try:
            if b.retry:
                umsg = {"id": None}
            else:
                umsg = await asyncio.to_thread(conversations.add_user, ws, cid, question, b.client_id)
            hist = await asyncio.to_thread(conversations.history, ws, cid)
        except conversations.NotFound:
            raise HTTPException(404, "conversation not found") from None
        except conversations.Duplicate:
            raise HTTPException(409, "This message was already sent.") from None
        if not hist or hist[-1]["role"] != "user":
            raise HTTPException(409, "There is no unanswered question to retry.")
        msgs = assistant.clean_messages(hist[-assistant.MAX_MESSAGES:])
        msgs = [{**m, "content": m["content"][:assistant.MAX_CONTENT]} for m in msgs]
        while msgs and sum(len(m["content"]) for m in msgs) > assistant.MAX_TOTAL and len(msgs) > 1:
            msgs.pop(0)                       # oldest first; the new question is always kept
        while msgs and msgs[0]["role"] != "user":
            msgs.pop(0)
        mid = await asyncio.to_thread(conversations.start_reply, ws, cid, {"provider": b.provider, "model": b.model})
        saved = {"type": "saved", "conversation_id": cid, "user_message_id": umsg["id"], "assistant_message_id": mid}
    else:
        msgs = assistant.clean_messages([m.model_dump() for m in b.messages])
    system = await asyncio.to_thread(assistant.system_prompt, ws, b.include_context)  # SQLite + graph work

    async def gen():
        text, status, meta = "", "stopped", {"provider": b.provider, "model": b.model}
        last = time.monotonic()

        async def flush(st: str, final: bool = False) -> None:
            if not saved:
                return
            try:
                await asyncio.to_thread(conversations.write_reply, ws, saved["assistant_message_id"], text, st,
                                        meta if final else None)
            except supa.DataError:
                pass   # storage hiccup: the answer still streams; the reader marks a stale row as interrupted

        if saved:
            yield f"data: {json.dumps(saved)}\n\n"
        try:
            async for ev in p.stream(model=b.model, system=system, messages=msgs, effort=effort):
                if await request.is_disconnected():
                    status = "stopped"
                    return  # closing the generator closes the upstream connection
                if ev.get("type") == "text":
                    text += ev.get("delta", "")
                    if time.monotonic() - last > FLUSH_S:
                        last = time.monotonic()
                        await flush("streaming")
                elif ev.get("type") == "done":
                    status = "complete"
                    meta.update({k: ev.get(k) for k in ("stop_reason", "usage", "request_id")})
                elif ev.get("type") == "error":
                    status = "error"
                    meta["error"] = {k: ev.get(k) for k in ("kind", "message", "hint", "retryable", "request_id")}
                yield f"data: {json.dumps(ev)}\n\n"
        except Exception:  # never leak a stack trace or a key into the stream
            status = "error"
            err = ProviderError('server', 'The assistant failed unexpectedly.').to_event()
            meta["error"] = {k: err.get(k) for k in ("kind", "message", "hint", "retryable")}
            yield f"data: {json.dumps(err)}\n\n"
        finally:
            # runs on completion, error, the user's Stop (client disconnect) and server shutdown alike
            await flush(status, final=True)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
