"""Assistant conversations are stored per workspace and survive anything the client does."""
import json
import time

import httpx
import pytest

from app import keys
from app.providers import anthropic_api
from conftest import sign_in
from fakes import ALICE, BOB


@pytest.fixture(autouse=True)
def _clean_keys():
    keys.clear()
    yield
    keys.clear()


def sse(*events):
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()


def answer(text):
    return lambda req: httpx.Response(200, content=sse(
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 3}},
        {"type": "message_stop"}))


def ask(client, cid, text, client_id=None, headers=None, retry=False):
    body = {"retry": retry, "provider": "anthropic", "model": "claude-opus-5-5", "messages": [{"role": "user", "content": text}],
            "include_context": False, "conversation_id": cid, "client_id": client_id or f"c{time.time_ns()}"}
    with client.stream("POST", "/api/assistant/chat", json=body, headers=headers or {}) as r:
        if r.status_code != 200:
            r.read()
            return r.status_code, r.json()
        return 200, [json.loads(ln[6:]) for ln in r.iter_lines() if ln.startswith("data: ")]


def test_conversation_crud_and_auto_title(client):
    sign_in(client, ALICE)
    c = client.post("/api/conversations", json={}).json()
    assert c["title"] == "New conversation"
    keys.set_many({"anthropic": "k"})
    import app.providers.anthropic_api as a
    a.TRANSPORT = httpx.MockTransport(answer("ok"))
    try:
        ask(client, c["id"], "Which path should I fix first?")
    finally:
        a.TRANSPORT = None
    listed = client.get("/api/conversations").json()["conversations"]
    assert listed[0]["title"] == "Which path should I fix first?"
    assert client.patch(f"/api/conversations/{c['id']}", json={"title": "  Triage  "}).json()["title"] == "Triage"
    assert client.delete(f"/api/conversations/{c['id']}").json() == {"ok": True}
    assert client.get(f"/api/conversations/{c['id']}/messages").status_code == 404


def test_messages_persist_in_order_and_the_model_sees_the_stored_history(client, monkeypatch):
    sign_in(client, ALICE)
    keys.set_many({"anthropic": "k"})
    sent = []

    def handler(req):
        sent.append(json.loads(req.content)["messages"])
        return answer(f"answer {len(sent)}")(req)

    monkeypatch.setattr(anthropic_api, "TRANSPORT", httpx.MockTransport(handler))
    cid = client.post("/api/conversations", json={}).json()["id"]
    status, evs = ask(client, cid, "first question")
    assert status == 200 and evs[0]["type"] == "saved" and evs[-1]["type"] == "done"
    ask(client, cid, "second question")
    # the second request carried the stored first turn, not whatever the client claimed
    assert [m["content"] for m in sent[1]] == ["first question", "answer 1", "second question"]
    msgs = client.get(f"/api/conversations/{cid}/messages").json()["messages"]
    assert [(m["role"], m["content"], m["status"]) for m in msgs] == [
        ("user", "first question", "complete"), ("assistant", "answer 1", "complete"),
        ("user", "second question", "complete"), ("assistant", "answer 2", "complete")]
    assert msgs[1]["meta"]["model"] == "claude-opus-5-5" and msgs[1]["meta"]["usage"]["output"] == 3
    assert all(msgs[i]["created"] <= msgs[i + 1]["created"] for i in range(3))


def test_a_resubmitted_message_is_not_stored_twice(client, monkeypatch):
    sign_in(client, ALICE)
    keys.set_many({"anthropic": "k"})
    monkeypatch.setattr(anthropic_api, "TRANSPORT", httpx.MockTransport(answer("ok")))
    cid = client.post("/api/conversations", json={}).json()["id"]
    assert ask(client, cid, "hello", client_id="dup-client-1")[0] == 200
    status, body = ask(client, cid, "hello", client_id="dup-client-1")
    assert status == 409 and "already sent" in body["detail"]
    assert len(client.get(f"/api/conversations/{cid}/messages").json()["messages"]) == 2


def test_failed_reply_is_kept_as_an_error_and_left_out_of_the_next_prompt(client, monkeypatch):
    sign_in(client, ALICE)
    keys.set_many({"anthropic": "k"})
    calls = []

    def handler(req):
        calls.append(json.loads(req.content)["messages"])
        if len(calls) == 1:
            return httpx.Response(401, json={"error": {"type": "authentication_error", "message": "invalid x-api-key"}})
        return answer("fine now")(req)

    monkeypatch.setattr(anthropic_api, "TRANSPORT", httpx.MockTransport(handler))
    cid = client.post("/api/conversations", json={}).json()["id"]
    _, evs = ask(client, cid, "one")
    assert evs[-1]["type"] == "error"
    msgs = client.get(f"/api/conversations/{cid}/messages").json()["messages"]
    assert msgs[1]["status"] == "error" and msgs[1]["meta"]["error"]["kind"] == "auth"
    ask(client, cid, "two")
    assert [m["role"] for m in calls[1]] == ["user"] and calls[1][0]["content"] == "one\n\ntwo"


def test_partial_reply_survives_a_crash_and_reads_back_as_interrupted(client, world, monkeypatch):
    sign_in(client, ALICE)
    cid = client.post("/api/conversations", json={}).json()["id"]
    ws = client.get("/api/workspaces").json()["active"]
    # what a killed app leaves behind: a reply row still marked streaming, last written long ago
    old = time.time() - 600
    world.db.add("messages", {"ws": ws, "conversation": cid, "user_id": ALICE, "role": "assistant",
                              "content": "The worst path starts at", "status": "streaming", "created": old, "updated": old})
    [m] = client.get(f"/api/conversations/{cid}/messages").json()["messages"]
    assert m["status"] == "interrupted" and m["content"] == "The worst path starts at"


def test_conversations_never_cross_workspaces_or_accounts(client):
    sign_in(client, ALICE)
    first = client.get("/api/workspaces").json()["active"]
    second = client.post("/api/workspaces", json={"name": "Second"}).json()["workspace"]["id"]
    a = client.post("/api/conversations", json={"title": "in first"}, headers={"X-Workspace": str(first)}).json()
    assert client.get("/api/conversations", headers={"X-Workspace": str(second)}).json()["conversations"] == []
    assert client.get(f"/api/conversations/{a['id']}/messages", headers={"X-Workspace": str(second)}).status_code == 404
    status, _ = ask(client, a["id"], "leak?", headers={"X-Workspace": str(second)})
    assert status == 404
    sign_in(client, BOB)
    assert client.get(f"/api/conversations/{a['id']}/messages").status_code == 404
    assert client.patch(f"/api/conversations/{a['id']}", json={"title": "x"}).status_code == 404


def test_deleting_a_workspace_deletes_its_conversations(client, world):
    sign_in(client, ALICE)
    ws = client.post("/api/workspaces", json={"name": "Temp"}).json()["workspace"]["id"]
    client.post("/api/conversations", json={"title": "t"}, headers={"X-Workspace": str(ws)})
    assert client.delete(f"/api/workspaces/{ws}").status_code == 200
    assert not [r for r in world.db.tables.get("conversations", []) if r["ws"] == ws]


def test_retry_answers_the_stored_question_without_storing_it_again(client, monkeypatch):
    sign_in(client, ALICE)
    keys.set_many({"anthropic": "k"})
    replies = iter([httpx.Response(529, json={"error": {"type": "overloaded_error", "message": "busy"}})] * 4)
    monkeypatch.setattr(anthropic_api, "TRANSPORT", httpx.MockTransport(lambda r: next(replies, None) or answer("recovered")(r)))
    from app.providers import base
    monkeypatch.setattr(base, "BACKOFF", (0, 0, 0))
    cid = client.post("/api/conversations", json={}).json()["id"]
    ask(client, cid, "what now?")
    assert ask(client, cid, "what now?", retry=True)[0] == 200
    msgs = client.get(f"/api/conversations/{cid}/messages").json()["messages"]
    assert [(m["role"], m["status"]) for m in msgs] == [("user", "complete"), ("assistant", "error"), ("assistant", "complete")]
    assert msgs[-1]["content"] == "recovered"
    # nothing left to retry once it is answered
    assert ask(client, cid, "what now?", retry=True)[0] == 409


def test_interrupted_reply_can_be_asked_again_and_titles_never_hold_a_key(client, world, monkeypatch):
    sign_in(client, ALICE)
    keys.set_many({"anthropic": "k"})
    monkeypatch.setattr(anthropic_api, "TRANSPORT", httpx.MockTransport(answer("second try")))
    cid = client.post("/api/conversations", json={}).json()["id"]
    ws = client.get("/api/workspaces").json()["active"]
    ask(client, cid, "why does sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWX fail?")
    title = client.get("/api/conversations").json()["conversations"][0]["title"]
    assert "ABCDEFGHIJKLMNOPQRSTUVWX" not in title
    # a later reply that was cut off mid-stream
    old = time.time() - 600
    world.db.add("messages", {"ws": ws, "conversation": cid, "user_id": ALICE, "role": "user", "content": "and now?",
                              "status": "complete", "created": old, "updated": old})
    world.db.add("messages", {"ws": ws, "conversation": cid, "user_id": ALICE, "role": "assistant", "content": "The wor",
                              "status": "streaming", "created": old, "updated": old})
    assert ask(client, cid, "and now?", retry=True)[0] == 200


def test_stored_history_is_bounded_before_it_reaches_the_provider(client, world, monkeypatch):
    sign_in(client, ALICE)
    keys.set_many({"anthropic": "k"})
    sent = []
    monkeypatch.setattr(anthropic_api, "TRANSPORT", httpx.MockTransport(
        lambda r: (sent.append(json.loads(r.content)["messages"]), answer("ok")(r))[1]))
    cid = client.post("/api/conversations", json={}).json()["id"]
    ws = client.get("/api/workspaces").json()["active"]
    t = time.time() - 1000
    for i in range(30):
        world.db.add("messages", {"ws": ws, "conversation": cid, "user_id": ALICE, "role": "user" if i % 2 == 0 else "assistant",
                                  "content": "x" * 7000, "status": "complete", "created": t + i, "updated": t + i})
    assert ask(client, cid, "latest question")[0] == 200
    total = sum(len(m["content"]) for m in sent[0])
    assert total <= 60000 + 8000 and sent[0][-1]["content"].endswith("latest question") and sent[0][0]["role"] == "user"
