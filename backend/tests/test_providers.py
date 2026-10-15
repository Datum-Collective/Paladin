"""Provider layer: wire format, error classification, streaming normalisation, key custody. No network: httpx
MockTransport stands in for both vendors, using the shapes documented by Anthropic and OpenAI."""
import asyncio
import json

import httpx
import pytest

from app import keys
from app.providers import ProviderError, base, get_provider
from app.providers import anthropic_api, openai_api


@pytest.fixture(autouse=True)
def _clean_keys():
    keys.clear()
    yield
    keys.clear()


def run(coro):
    return asyncio.run(coro)


def sse(*events):
    out = ""
    for name, data in events:
        out += (f"event: {name}\n" if name else "") + f"data: {json.dumps(data)}\n\n"
    return out.encode()


async def collect(agen):
    return [e async for e in agen]


def use(monkeypatch, module, handler):
    monkeypatch.setattr(module, "TRANSPORT", httpx.MockTransport(handler))


# ---- key custody ----
def test_keys_memory_overrides_env_and_never_logs(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    assert keys.get("ANTHROPIC_API_KEY") == "env-key"
    keys.set_many({"anthropic": "mem-key"})
    assert keys.get("ANTHROPIC_API_KEY") == "mem-key"
    keys.set_many({"anthropic": None})
    assert keys.get("ANTHROPIC_API_KEY") == "env-key"
    assert "mem-key" not in repr(keys.status())


def test_keys_reject_unknown_provider_and_bad_values():
    with pytest.raises(ValueError):
        keys.set_many({"nope": "x"})
    with pytest.raises(ValueError):
        keys.set_many({"openai": "has space"})
    with pytest.raises(ValueError):
        keys.set_many({"openai": "x" * 600})


# ---- error classification ----
@pytest.mark.parametrize("status,body,headers,kind,retryable", [
    (401, {"type": "error", "error": {"type": "authentication_error", "message": "bad key"}}, {}, "auth", False),
    (402, {"type": "error", "error": {"type": "billing_error", "message": "x"}}, {}, "quota", False),
    (403, {"type": "error", "error": {"type": "permission_error", "message": "x"}}, {}, "permission", False),
    (404, {"type": "error", "error": {"type": "not_found_error", "message": "x"}}, {}, "not_found", False),
    (413, {"type": "error", "error": {"type": "request_too_large", "message": "x"}}, {}, "too_large", False),
    (429, {"type": "error", "error": {"type": "rate_limit_error", "message": "x"}}, {"retry-after": "3"}, "rate_limit", True),
    (429, {"type": "error", "error": {"type": "rate_limit_error", "message": "spend", "error_code": "enforced_spend_limit_reached"}},
     {}, "quota", False),
    (500, {"type": "error", "error": {"type": "api_error", "message": "x"}}, {}, "server", True),
    (529, {"type": "error", "error": {"type": "overloaded_error", "message": "x"}}, {}, "overloaded", True),
    (400, {"type": "error", "error": {"type": "invalid_request_error", "message": "x"}}, {}, "invalid", False),
])
def test_anthropic_error_classification(status, body, headers, kind, retryable):
    e = anthropic_api.classify(status, body, {**headers, "request-id": "req_1"})
    assert (e.kind, e.retryable, e.request_id) == (kind, retryable, "req_1")
    assert e.message and "Oops" not in e.message


@pytest.mark.parametrize("status,body,kind,retryable", [
    (401, {"error": {"message": "bad", "type": "invalid_request_error", "code": "invalid_api_key"}}, "auth", False),
    (429, {"error": {"message": "slow", "type": "requests", "code": "rate_limit_exceeded"}}, "rate_limit", True),
    (429, {"error": {"message": "out", "type": "insufficient_quota", "code": "insufficient_quota"}}, "quota", False),
    (429, {"error": {"message": "out", "type": "x", "code": "credit_balance_exhausted"}}, "quota", False),
    (429, {"error": {"message": "cap", "type": "x", "code": "organization_spend_limit_exceeded"}}, "quota", False),
    (503, {"error": {"message": "busy", "type": "server_error", "code": None}}, "server", True),
    (404, {"error": {"message": "no model", "type": "invalid_request_error", "code": "model_not_found"}}, "not_found", False),
])
def test_openai_error_classification(status, body, kind, retryable):
    e = openai_api.classify(status, body, {"x-request-id": "req_9"})
    assert (e.kind, e.retryable, e.request_id) == (kind, retryable, "req_9")


def test_error_event_shape_has_fix_guidance():
    ev = ProviderError("auth", "bad", status=401, request_id="r").to_event()
    assert ev["type"] == "error" and ev["kind"] == "auth" and ev["request_id"] == "r"
    assert base.guidance("auth") in ev["message"] or ev["hint"] == base.guidance("auth")


# ---- Anthropic ----
def test_anthropic_models_listing_filters_retired_and_sends_headers(monkeypatch):
    keys.set_many({"anthropic": "sk-ant-test"})
    seen = {}

    def handler(req: httpx.Request):
        seen.update(req.headers)
        return httpx.Response(200, json={"data": [
            {"id": "claude-opus-5-5", "display_name": "Claude Opus 5.5", "max_tokens": 128000, "max_input_tokens": 1000000,
             "lifecycle": "active", "capabilities": {"thinking": {"supported": True}}},
            {"id": "claude-old", "display_name": "Old", "lifecycle": "retired"},
        ], "has_more": False})

    use(monkeypatch, anthropic_api, handler)
    models = run(get_provider("anthropic").list_models())
    assert [m["id"] for m in models] == ["claude-opus-5-5"]
    assert models[0]["name"] == "Claude Opus 5.5" and models[0]["max_output"] == 128000
    assert seen["x-api-key"] == "sk-ant-test" and seen["anthropic-version"] == "2023-06-01"


def test_anthropic_stream_normalises_events_and_omits_banned_params(monkeypatch):
    keys.set_many({"anthropic": "k"})
    sent = {}

    def handler(req: httpx.Request):
        sent.update(json.loads(req.content))
        return httpx.Response(200, headers={"request-id": "req_a", "content-type": "text/event-stream"}, content=sse(
            ("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": 12}}}),
            ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
            ("ping", {"type": "ping"}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hel"}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "lo"}}),
            ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 5}}),
            ("message_stop", {"type": "message_stop"}),
        ))

    use(monkeypatch, anthropic_api, handler)
    evs = run(collect(get_provider("anthropic").stream(
        model="claude-opus-5-5", system="sys", messages=[{"role": "user", "content": "hi"}], effort="high")))
    assert "".join(e["delta"] for e in evs if e["type"] == "text") == "Hello"
    done = evs[-1]
    assert done == {"type": "done", "stop_reason": "end_turn", "usage": {"input": 12, "output": 5}, "request_id": "req_a"}
    for banned in ("temperature", "top_k", "top_p", "tool_choice"):
        assert banned not in sent
    assert sent["stream"] is True and sent["system"] == "sys" and sent["output_config"] == {"effort": "high"}
    assert sent["messages"][-1]["role"] == "user"   # never prefill


def test_anthropic_in_stream_error_becomes_error_event(monkeypatch):
    keys.set_many({"anthropic": "k"})
    use(monkeypatch, anthropic_api, lambda r: httpx.Response(200, content=sse(
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "par"}}),
        ("error", {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}),
    )))
    evs = run(collect(get_provider("anthropic").stream(model="m", system="", messages=[{"role": "user", "content": "x"}])))
    assert evs[0]["type"] == "text"
    assert evs[-1]["type"] == "error" and evs[-1]["kind"] == "overloaded" and evs[-1]["retryable"] is True


def test_anthropic_refusal_and_truncation_are_states_not_errors(monkeypatch):
    keys.set_many({"anthropic": "k"})
    for reason in ("refusal", "max_tokens"):
        use(monkeypatch, anthropic_api, lambda r, reason=reason: httpx.Response(200, content=sse(
            ("message_delta", {"type": "message_delta", "delta": {"stop_reason": reason}, "usage": {"output_tokens": 1}}),
            ("message_stop", {"type": "message_stop"}))))
        evs = run(collect(get_provider("anthropic").stream(model="m", system="", messages=[{"role": "user", "content": "x"}])))
        assert evs[-1]["type"] == "done" and evs[-1]["stop_reason"] == reason


def test_anthropic_retries_connection_phase_then_succeeds(monkeypatch):
    keys.set_many({"anthropic": "k"})
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(529, json={"type": "error", "error": {"type": "overloaded_error", "message": "x"}})
        return httpx.Response(200, content=sse(("message_stop", {"type": "message_stop"})))

    use(monkeypatch, anthropic_api, handler)
    monkeypatch.setattr(base, "BACKOFF", (0, 0, 0))
    evs = run(collect(get_provider("anthropic").stream(model="m", system="", messages=[{"role": "user", "content": "x"}])))
    assert calls["n"] == 3 and evs[-1]["type"] == "done"


def test_anthropic_never_retries_spend_cap_or_auth(monkeypatch):
    keys.set_many({"anthropic": "k"})
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(401, json={"type": "error", "error": {"type": "authentication_error", "message": "bad"}})

    use(monkeypatch, anthropic_api, handler)
    monkeypatch.setattr(base, "BACKOFF", (0, 0, 0))
    evs = run(collect(get_provider("anthropic").stream(model="m", system="", messages=[{"role": "user", "content": "x"}])))
    assert calls["n"] == 1 and evs[-1]["kind"] == "auth"


def test_missing_key_is_an_auth_error_without_network(monkeypatch):
    use(monkeypatch, anthropic_api, lambda r: pytest.fail("must not call the network"))
    evs = run(collect(get_provider("anthropic").stream(model="m", system="", messages=[{"role": "user", "content": "x"}])))
    assert evs[-1]["kind"] == "auth"


# ---- OpenAI ----
def test_openai_models_are_filtered_to_chat_capable_and_unshuttered(monkeypatch):
    keys.set_many({"openai": "sk-test"})
    seen = {}

    def handler(req):
        seen.update(req.headers)
        ids = ["gpt-5.6-sol", "text-embedding-3-large", "whisper-1", "gpt-4o-mini-tts", "o4-mini", "dall-e-3", "gpt-old"]
        return httpx.Response(200, json={"object": "list", "data": [
            {"id": i, "object": "model", "created": 100 + n, "owned_by": "openai",
             **({"shutdown_date": "2026-01-01"} if i == "gpt-old" else {})} for n, i in enumerate(ids)]})

    use(monkeypatch, openai_api, handler)
    models = run(get_provider("openai").list_models())
    assert sorted(m["id"] for m in models) == ["gpt-5.6-sol", "o4-mini"]
    assert seen["authorization"] == "Bearer sk-test"


def test_openai_stream_uses_responses_api_with_store_false(monkeypatch):
    keys.set_many({"openai": "k"})
    sent = {}

    def handler(req):
        sent.update(json.loads(req.content))
        sent["_path"] = req.url.path
        return httpx.Response(200, headers={"x-request-id": "req_o"}, content=sse(
            (None, {"type": "response.created", "response": {"id": "resp_1"}}),
            (None, {"type": "response.output_text.delta", "delta": "Hi"}),
            (None, {"type": "response.output_text.delta", "delta": " there"}),
            (None, {"type": "response.completed", "response": {"status": "completed",
                                                              "usage": {"input_tokens": 7, "output_tokens": 3}}}),
        ))

    use(monkeypatch, openai_api, handler)
    evs = run(collect(get_provider("openai").stream(
        model="gpt-5.6-sol", system="be brief", messages=[{"role": "user", "content": "yo"}], effort="medium")))
    assert sent["_path"].endswith("/v1/responses")
    assert sent["store"] is False and sent["stream"] is True and sent["instructions"] == "be brief"
    assert sent["reasoning"] == {"effort": "medium"} and sent["max_output_tokens"] >= 4000
    assert "".join(e["delta"] for e in evs if e["type"] == "text") == "Hi there"
    assert evs[-1] == {"type": "done", "stop_reason": "end_turn", "usage": {"input": 7, "output": 3}, "request_id": "req_o"}


def test_openai_stream_accepts_full_lifecycle_and_refusal_events(monkeypatch):
    keys.set_many({"openai": "k"})
    progress = [
        "response.created", "response.queued", "response.in_progress",
        "response.output_item.added", "response.content_part.added",
        "response.output_text.done", "response.content_part.done", "response.output_item.done",
        "response.reasoning_summary_part.added", "response.reasoning_summary_text.delta",
        "response.reasoning_summary_text.done", "response.reasoning_summary_part.done",
        "response.function_call_arguments.delta", "response.function_call_arguments.done",
        "response.refusal.done",
    ]
    events = [(None, {"type": t}) for t in progress]
    events.insert(5, (None, {"type": "response.refusal.delta", "delta": "I cannot"}))
    events.append((None, {"type": "response.completed", "response": {"usage": {}}}))
    use(monkeypatch, openai_api, lambda r: httpx.Response(200, content=sse(*events)))

    evs = run(collect(get_provider("openai").stream(
        model="gpt-5", system="", messages=[{"role": "user", "content": "x"}])))

    assert evs[0] == {"type": "text", "delta": "I cannot"}
    assert evs[-1]["type"] == "done"


def test_openai_incomplete_and_failed(monkeypatch):
    keys.set_many({"openai": "k"})
    use(monkeypatch, openai_api, lambda r: httpx.Response(200, content=sse(
        (None, {"type": "response.incomplete", "response": {"status": "incomplete",
                                                            "incomplete_details": {"reason": "max_output_tokens"}}}))))
    evs = run(collect(get_provider("openai").stream(model="m", system="", messages=[{"role": "user", "content": "x"}])))
    assert evs[-1]["type"] == "done" and evs[-1]["stop_reason"] == "max_tokens"
    use(monkeypatch, openai_api, lambda r: httpx.Response(200, content=sse(
        (None, {"type": "response.failed", "response": {"error": {"code": "server_error", "message": "boom"}}}))))
    evs = run(collect(get_provider("openai").stream(model="m", system="", messages=[{"role": "user", "content": "x"}])))
    assert evs[-1]["type"] == "error" and evs[-1]["kind"] == "server"


def test_openai_quota_429_is_not_retried(monkeypatch):
    keys.set_many({"openai": "k"})
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(429, json={"error": {"message": "q", "type": "insufficient_quota", "code": "insufficient_quota"}})

    use(monkeypatch, openai_api, handler)
    monkeypatch.setattr(base, "BACKOFF", (0, 0, 0))
    evs = run(collect(get_provider("openai").stream(model="m", system="", messages=[{"role": "user", "content": "x"}])))
    assert calls["n"] == 1 and evs[-1]["kind"] == "quota" and evs[-1]["retryable"] is False


# ---- validation ----
def test_validate_reports_ok_and_failure(monkeypatch):
    keys.set_many({"openai": "k"})
    use(monkeypatch, openai_api, lambda r: httpx.Response(200, json={"data": []}))
    assert run(get_provider("openai").validate())["ok"] is True
    use(monkeypatch, openai_api, lambda r: httpx.Response(401, json={"error": {"message": "bad", "code": "invalid_api_key"}}))
    v = run(get_provider("openai").validate())
    assert v["ok"] is False and v["error"]["kind"] == "auth"


def test_mid_stream_network_drop_is_reported_not_replayed(monkeypatch):
    keys.set_many({"anthropic": "k"})
    calls = {"n": 0}

    class Boom(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"par"}}\n\n'
            raise httpx.ReadError("dropped")

    def handler(req):
        calls["n"] += 1
        return httpx.Response(200, stream=Boom())

    use(monkeypatch, anthropic_api, handler)
    monkeypatch.setattr(base, "BACKOFF", (0, 0, 0))
    evs = run(collect(get_provider("anthropic").stream(model="m", system="", messages=[{"role": "user", "content": "x"}])))
    assert calls["n"] == 1
    assert evs[0] == {"type": "text", "delta": "par"} and evs[-1]["type"] == "error" and evs[-1]["kind"] == "network"


@pytest.mark.parametrize("module,name,body", [
    (anthropic_api, "anthropic", sse(("content_block_delta", {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "x"}}))),
    (openai_api, "openai", sse((None, {"type": "response.output_text.delta", "delta": "x"}))),
])
def test_stream_that_ends_without_terminal_event_is_an_error_not_done(monkeypatch, module, name, body):
    keys.set_many({name: "k"})
    use(monkeypatch, module, lambda r: httpx.Response(200, content=body))
    evs = run(collect(get_provider(name).stream(model="m", system="", messages=[{"role": "user", "content": "x"}])))
    assert evs[-1]["type"] == "error" and "ended early" in evs[-1]["message"]


def test_models_with_html_body_is_a_classified_error(monkeypatch):
    keys.set_many({"openai": "k"})
    use(monkeypatch, openai_api, lambda r: httpx.Response(502, content=b"<html>bad gateway</html>"))
    monkeypatch.setattr(base, "BACKOFF", (0, 0, 0))
    with pytest.raises(ProviderError) as e:
        run(get_provider("openai").list_models())
    assert e.value.kind == "server"


def test_key_with_trailing_newline_is_rejected():
    with pytest.raises(ValueError):
        keys.set_many({"openai": "sk-abc\n"})
