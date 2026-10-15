"""HTTP surface for providers and the grounded assistant."""
import json

import httpx
import pytest

from app import keys
from app.providers import anthropic_api, openai_api
from conftest import sign_in

TOKEN = "t" * 40
LOG = ("May 14 13:05:11 WEB-BO-01 sshd[912]: Accepted password for www-data from 185.199.110.42 port 51544 ssh2")


@pytest.fixture(autouse=True)
def _clean_keys():
    keys.clear()
    yield
    keys.clear()


def login(c):
    sign_in(c)


def sse(*events):
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()


def test_providers_require_auth(client):
    assert client.get("/api/providers").status_code == 401
    assert client.post("/api/assistant/chat", json={}).status_code == 401


def test_providers_list_reports_configuration_without_secrets(client):
    login(client)
    keys.set_many({"openai": "sk-secret-value"})
    r = client.get("/api/providers")
    assert r.status_code == 200
    by = {p["id"]: p for p in r.json()["providers"]}
    assert by["openai"]["configured"] is True and by["anthropic"]["configured"] is False
    assert "sk-secret-value" not in r.text


def test_key_push_requires_desktop_token_and_never_echoes(client, monkeypatch):
    monkeypatch.setenv("DESKTOP_MODE", "1")
    monkeypatch.setenv("APC_DESKTOP_TOKEN", TOKEN)
    assert client.put("/api/providers/keys", json={"openai": "k"}).status_code == 403
    r = client.put("/api/providers/keys", json={"openai": "sk-abc", "github": None}, headers={"X-Desktop-Token": TOKEN})
    assert r.status_code == 200 and "sk-abc" not in r.text
    assert r.json()["openai"] is True
    assert keys.get("OPENAI_API_KEY") == "sk-abc"


def test_key_push_disabled_outside_desktop_mode(client):
    assert client.put("/api/providers/keys", json={"openai": "k"}, headers={"X-Desktop-Token": TOKEN}).status_code == 404


def test_key_push_rejects_bad_values(client, monkeypatch):
    monkeypatch.setenv("DESKTOP_MODE", "1")
    monkeypatch.setenv("APC_DESKTOP_TOKEN", TOKEN)
    r = client.put("/api/providers/keys", json={"openai": "has space"}, headers={"X-Desktop-Token": TOKEN})
    assert r.status_code == 422


def test_models_endpoint_and_unknown_provider(client, monkeypatch):
    login(client)
    keys.set_many({"anthropic": "k"})
    monkeypatch.setattr(anthropic_api, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(
        200, json={"data": [{"id": "claude-opus-5-5", "display_name": "Opus", "lifecycle": "active"}]})))
    r = client.get("/api/providers/anthropic/models")
    assert r.status_code == 200 and r.json()["models"][0]["id"] == "claude-opus-5-5"
    assert client.get("/api/providers/nope/models").status_code == 404


def test_models_without_key_is_a_clear_auth_error(client):
    login(client)
    r = client.get("/api/providers/openai/models")
    assert r.status_code == 401 and "API key" in r.json()["detail"]


def _chat(client, **body):
    base = {"provider": "anthropic", "model": "claude-opus-5-5",
            "messages": [{"role": "user", "content": "What is the worst path?"}], "include_context": True}
    with client.stream("POST", "/api/assistant/chat", json={**base, **body}) as r:
        assert r.status_code == 200
        return [json.loads(ln[6:]) for ln in r.iter_lines() if ln.startswith("data: ")]


def test_chat_streams_normalised_events_and_grounds_on_workspace(client, monkeypatch):
    login(client)
    client.post("/api/ingest", json={"format": "linux_auth", "lines": [LOG]})
    keys.set_many({"anthropic": "k"})
    captured = {}

    def handler(req):
        captured.update(json.loads(req.content))
        return httpx.Response(200, content=sse(
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "The worst path is X."}},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 4}},
            {"type": "message_stop"}))

    monkeypatch.setattr(anthropic_api, "TRANSPORT", httpx.MockTransport(handler))
    evs = _chat(client)
    assert evs[0]["type"] == "text" and evs[-1]["type"] == "done"
    assert "paths" in captured["system"] and "WEB-BO-01" in captured["system"]
    assert "sk-" not in captured["system"]


def test_chat_context_is_redacted(client, monkeypatch):
    login(client)
    keys.set_many({"openai": "k"})
    captured = {}
    monkeypatch.setattr(openai_api, "TRANSPORT", httpx.MockTransport(lambda r: (captured.update(json.loads(r.content)),
        httpx.Response(200, content=sse({"type": "response.completed", "response": {"status": "completed", "usage": {}}})))[1]))
    _chat(client, provider="openai", model="gpt-x",
          messages=[{"role": "user", "content": "key is sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWX and ghp_abcdefghijklmnopqrstuvwxyz0123456789"}])
    sent = json.dumps(captured)
    assert "ABCDEFGHIJKLMNOPQRSTUVWX" not in sent and "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in sent


def test_chat_validates_input(client):
    login(client)
    bad = [
        {"provider": "nope", "model": "m", "messages": [{"role": "user", "content": "x"}]},
        {"provider": "openai", "model": "m", "messages": []},
        {"provider": "openai", "model": "m", "messages": [{"role": "system", "content": "x"}]},
        {"provider": "openai", "model": "m", "messages": [{"role": "user", "content": "x" * 9000}]},
        {"provider": "openai", "model": "m", "messages": [{"role": "assistant", "content": "x"}]},
    ]
    for b in bad:
        assert client.post("/api/assistant/chat", json=b).status_code in (404, 422), b


def test_chat_without_key_streams_an_auth_error_event(client):
    login(client)
    evs = _chat(client, provider="openai", model="gpt-x")
    assert evs[-1]["type"] == "error" and evs[-1]["kind"] == "auth"


def test_context_is_valid_json_and_keeps_fixes_when_over_budget(client):
    from app import assistant
    login(client)
    client.post("/api/ingest", json={"format": "linux_auth", "lines": [LOG]})
    ws = client.get("/api/workspaces").json()["active"]
    from app import supa
    from fakes import DEMO, access_token
    supa.set_user(access_token(DEMO), DEMO)   # outside a request: act as the signed-in user, as a request would
    for limit in (7000, 1500, 600):
        data = json.loads(assistant.context(ws, limit=limit))
        assert "fixes" in data and "paths" in data
        assert len(assistant.context(ws, limit=limit)) <= max(limit, len(json.dumps({"fixes": data["fixes"]})) + 200)


# ---- setup: a real inference round-trip with the saved key and chosen model ----
def _ok_stream(req):
    return httpx.Response(200, content=sse(
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ok"}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 1}},
        {"type": "message_stop"}))


def test_provider_test_round_trips_with_saved_key_and_model(client, monkeypatch):
    login(client)
    keys.set_many({"anthropic": "k"})
    seen = {}
    monkeypatch.setattr(anthropic_api, "TRANSPORT", httpx.MockTransport(
        lambda r: (seen.update(json.loads(r.content), key=r.headers.get("x-api-key")), _ok_stream(r))[1]))
    r = client.post("/api/providers/anthropic/test", json={"model": "claude-opus-5-5"})
    assert r.status_code == 200 and r.json() == {"ok": True, "model": "claude-opus-5-5"}
    assert seen["model"] == "claude-opus-5-5" and seen["key"] == "k" and seen["max_tokens"] <= 64


@pytest.mark.parametrize("status,body,kind", [
    (401, {"error": {"type": "authentication_error", "message": "invalid x-api-key"}}, "auth"),
    (404, {"error": {"type": "not_found_error", "message": "model: nope"}}, "not_found"),
    (402, {"error": {"type": "billing_error", "message": "credit balance is too low"}}, "quota"),
])
def test_provider_test_reports_failures_without_leaking_the_key(client, monkeypatch, status, body, kind):
    login(client)
    keys.set_many({"anthropic": "sk-ant-secretsecretsecret"})
    monkeypatch.setattr(anthropic_api, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(status, json=body)))
    r = client.post("/api/providers/anthropic/test", json={"model": "nope"})
    assert r.status_code == 200 and r.json()["ok"] is False
    assert r.json()["error"]["kind"] == kind and r.json()["error"]["hint"]
    assert "secretsecret" not in r.text


def test_provider_test_without_key_and_bad_input(client):
    login(client)
    r = client.post("/api/providers/openai/test", json={"model": "gpt-x"})
    assert r.status_code == 200 and r.json()["error"]["kind"] == "auth"
    assert client.post("/api/providers/nope/test", json={"model": "m"}).status_code == 404
    assert client.post("/api/providers/openai/test", json={"model": ""}).status_code == 422
    assert client.post("/api/providers/openai/test", json={}).status_code == 422


def test_setup_prefs_persist_and_reject_bad_values(client):
    login(client)
    p = client.get("/api/prefs").json()
    assert p["general.setup_done"] is False and p["general.setup_skipped"] is False
    r = client.put("/api/prefs", json={"general.setup_done": True, "assistant.provider": "openai", "assistant.model": "gpt-x"})
    assert r.status_code == 200 and r.json()["general.setup_done"] is True
    assert client.get("/api/prefs").json()["assistant.provider"] == "openai"
    assert client.put("/api/prefs", json={"general.setup_done": "yes"}).status_code == 422


def test_provider_test_turns_unexpected_exceptions_into_a_reason(client, monkeypatch):
    from app.providers import get_provider
    login(client)

    async def boom(model):
        raise KeyError("choices")
    monkeypatch.setattr(get_provider("anthropic"), "probe", boom)
    r = client.post("/api/providers/anthropic/test", json={"model": "m"})
    assert r.status_code == 200 and r.json()["ok"] is False and r.json()["error"]["kind"] == "server"
