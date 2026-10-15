"""Assistant conversations, stored per workspace (supabase/migrations/0004_conversations.sql).

Every read and write names the workspace, and a conversation is looked up inside that workspace before anything
touches its messages, so a message can never land in, or be read from, another workspace. Provider keys never
reach these rows: only what the user typed and what the model answered (both passed through assistant.redact).
"""
import time

from . import assistant, supa

TITLE_MAX = 120
DEFAULT_TITLE = "New conversation"
STALE_S = 90          # a reply still marked "streaming" this long after its last write was cut off (app closed)


class NotFound(Exception):
    pass


class Duplicate(Exception):
    """The same client message was already submitted; carries the stored row."""

    def __init__(self, row: dict):
        super().__init__("duplicate message")
        self.row = row


def _title(text: str) -> str:
    t = " ".join((text or "").split())[:TITLE_MAX].strip()
    return t or DEFAULT_TITLE


def list_for(ws: int) -> list[dict]:
    return supa.select("conversations", {"ws": supa.eq(ws)}, columns="id,title,created,updated", order="updated.desc")


def get(ws: int, cid: int) -> dict:
    row = supa.first("conversations", {"id": supa.eq(cid), "ws": supa.eq(ws)}, columns="id,title,created,updated")
    if not row:
        raise NotFound(cid)
    return row


def create(ws: int, title: str = "") -> dict:
    now = time.time()
    return supa.insert("conversations", {"ws": ws, "user_id": supa.user_id(), "title": _title(title), "created": now,
                                         "updated": now})[0]


def rename(ws: int, cid: int, title: str) -> dict:
    get(ws, cid)
    rows = supa.update("conversations", {"id": supa.eq(cid), "ws": supa.eq(ws)}, {"title": _title(title)})
    return {k: rows[0][k] for k in ("id", "title", "created", "updated")}


def delete(ws: int, cid: int) -> None:
    get(ws, cid)
    supa.delete("messages", {"conversation": supa.eq(cid), "ws": supa.eq(ws)})
    supa.delete("conversations", {"id": supa.eq(cid), "ws": supa.eq(ws)})


def _shape(r: dict, now: float) -> dict:
    status = r["status"]
    if status == "streaming" and now - float(r["updated"]) > STALE_S:
        status = "interrupted"      # the writer is gone: keep what arrived and say it is incomplete
    return {"id": r["id"], "role": r["role"], "content": r["content"], "status": status, "meta": r.get("meta") or {},
            "created": r["created"], "client_id": r.get("client_id")}


def messages(ws: int, cid: int) -> list[dict]:
    get(ws, cid)
    rows = supa.select("messages", {"conversation": supa.eq(cid), "ws": supa.eq(ws)}, order="id.asc")
    now = time.time()
    return [_shape(r, now) for r in rows]


def history(ws: int, cid: int) -> list[dict]:
    """What the model sees: finished turns only, in order. A failed or empty reply is left out, and consecutive user
    turns (a reply that failed in between) are merged so the conversation still alternates."""
    out: list[dict] = []
    for m in messages(ws, cid):
        if m["role"] == "assistant" and (m["status"] in ("error",) or not m["content"].strip()):
            continue
        if out and out[-1]["role"] == m["role"]:
            out[-1] = {"role": m["role"], "content": out[-1]["content"] + "\n\n" + m["content"]}
        else:
            out.append({"role": m["role"], "content": m["content"]})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def add_user(ws: int, cid: int, content: str, client_id: str | None) -> dict:
    conv = get(ws, cid)
    if client_id:
        dup = supa.first("messages", {"conversation": supa.eq(cid), "ws": supa.eq(ws), "client_id": supa.eq(client_id)})
        if dup:
            raise Duplicate(_shape(dup, time.time()))
    now = time.time()
    row = supa.insert("messages", {"ws": ws, "conversation": cid, "user_id": supa.user_id(), "client_id": client_id,
                                   "role": "user", "content": assistant.redact(content), "status": "complete",
                                   "created": now, "updated": now})[0]
    patch = {"updated": now}
    if conv["title"] == DEFAULT_TITLE:
        patch["title"] = _title(content)[:60]
    supa.update("conversations", {"id": supa.eq(cid), "ws": supa.eq(ws)}, patch, returning=None)
    return _shape(row, now)


def start_reply(ws: int, cid: int, meta: dict) -> int:
    now = time.time()
    return supa.insert("messages", {"ws": ws, "conversation": cid, "user_id": supa.user_id(), "role": "assistant",
                                    "content": "", "status": "streaming", "meta": meta, "created": now,
                                    "updated": now}, returning="id")[0]["id"]


def write_reply(ws: int, mid: int, content: str, status: str = "streaming", meta: dict | None = None) -> None:
    vals = {"content": assistant.redact(content)[:40000], "status": status, "updated": time.time()}
    if meta is not None:
        vals["meta"] = meta
    supa.update("messages", {"id": supa.eq(mid), "ws": supa.eq(ws)}, vals, returning=None)
