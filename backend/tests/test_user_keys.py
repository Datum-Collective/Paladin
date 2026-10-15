"""A signed-in user pastes their own model key: held per user in memory, checked against the provider, never echoed."""
import httpx
import pytest

from app import ai, keys
from app.providers import anthropic_api, openai_api
from conftest import client_as
from fakes import ALICE, DEMO

OTHER = ALICE
GOOD = "sk-ant-" + "a" * 40


@pytest.fixture(autouse=True)
def _clean():
    keys.clear()
    ai._models.clear()
    yield
    keys.clear()


def provider_ok(monkeypatch, module, status=200, body=None):
    def handler(req):
        return httpx.Response(status, json=body if body is not None else {"data": [{"id": "m1"}]})
    monkeypatch.setattr(module, "TRANSPORT", httpx.MockTransport(handler))


def test_paste_key_is_checked_stored_and_never_echoed(world, monkeypatch):
    provider_ok(monkeypatch, anthropic_api)
    with client_as(DEMO) as c:
        r = c.put("/api/providers/anthropic/key", json={"key": GOOD})
        assert r.status_code == 200 and r.json()["ok"] is True and GOOD not in r.text
        listing = c.get("/api/providers").json()
        assert {p["id"]: p["configured"] for p in listing["providers"]}["anthropic"] is True
        assert GOOD not in str(listing)


def test_rejected_key_is_not_kept(world, monkeypatch):
    provider_ok(monkeypatch, anthropic_api, 401, {"error": {"type": "authentication_error", "message": "invalid x-api-key"}})
    with client_as(DEMO) as c:
        r = c.put("/api/providers/anthropic/key", json={"key": GOOD})
        assert r.status_code == 200 and r.json()["ok"] is False and r.json()["error"]["kind"] == "auth"
        assert {p["id"]: p["configured"] for p in c.get("/api/providers").json()["providers"]}["anthropic"] is False


def test_keys_are_private_to_each_user(world, monkeypatch):
    provider_ok(monkeypatch, anthropic_api)
    with client_as(DEMO) as a, client_as(OTHER) as b:
        assert a.put("/api/providers/anthropic/key", json={"key": GOOD}).json()["ok"] is True
        mine = {p["id"]: p["configured"] for p in a.get("/api/providers").json()["providers"]}
        theirs = {p["id"]: p["configured"] for p in b.get("/api/providers").json()["providers"]}
        assert mine["anthropic"] is True and theirs["anthropic"] is False


def test_remove_key(world, monkeypatch):
    provider_ok(monkeypatch, openai_api)
    with client_as(DEMO) as c:
        assert c.put("/api/providers/openai/key", json={"key": "sk-" + "b" * 40}).json()["ok"] is True
        assert c.delete("/api/providers/openai/key").json()["providers"]["openai"] is False


def test_unknown_provider_and_github_are_refused(world):
    with client_as(DEMO) as c:
        assert c.put("/api/providers/github/key", json={"key": "x" * 30}).status_code == 404
        assert c.put("/api/providers/anthropic/key", json={"key": "has space"}).status_code == 422


def test_requires_sign_in(client):
    assert client.put("/api/providers/anthropic/key", json={"key": GOOD}).status_code == 401


def fake_httpx(monkeypatch, routes, seen):
    def post(url, headers=None, json=None, timeout=None):
        seen.append((url, headers, json))
        return routes(url, json)
    def get(url, headers=None, timeout=None):
        seen.append((url, headers, None))
        return httpx.Response(200, json={"data": [{"id": "gpt-5-mini", "created": 5}, {"id": "text-embedding-3", "created": 9}]},
                              request=httpx.Request("GET", url))
    monkeypatch.setattr(ai.httpx, "post", post)
    monkeypatch.setattr(ai.httpx, "get", get)


def test_ai_uses_claude_with_x_api_key(monkeypatch):
    seen = []
    fake_httpx(monkeypatch, lambda u, j: httpx.Response(
        200, json={"content": [{"type": "text", "text": "hello"}]}, request=httpx.Request("POST", u)), seen)
    keys.set_user_key("u1", "anthropic", GOOD)
    keys.bind("u1")
    assert ai.complete("sys", "hi") == "hello"
    url, headers, body = seen[0]
    assert url.endswith("/v1/messages") and headers["x-api-key"] == GOOD and headers["anthropic-version"] == "2023-06-01"
    assert body["messages"][0]["content"] == "hi" and body["system"] == "sys"


def test_ai_falls_back_to_openai_bearer_responses_api(monkeypatch):
    seen = []
    out = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "from openai"}]}]}
    fake_httpx(monkeypatch, lambda u, j: httpx.Response(200, json=out, request=httpx.Request("POST", u)), seen)
    key = "sk-" + "c" * 40
    keys.set_user_key("u2", "openai", key)
    keys.bind("u2")
    assert ai.enabled() and ai.provider() == "openai"
    assert ai.complete("sys", "hi") == "from openai"
    post = [s for s in seen if s[2] is not None][0]
    assert post[0].endswith("/v1/responses") and post[1]["Authorization"] == f"Bearer {key}"
    assert post[2]["model"] == "gpt-5-mini" and post[2]["instructions"] == "sys" and post[2]["store"] is False


def test_ai_off_without_key_and_fails_closed(monkeypatch):
    keys.bind("nobody")
    assert ai.enabled() is False and ai.complete("s", "u") is None
    keys.set_user_key("u3", "anthropic", GOOD)
    keys.bind("u3")
    def boom(*a, **k): raise httpx.ConnectError("down")
    monkeypatch.setattr(ai.httpx, "post", boom)
    assert ai.complete("s", "u") is None
