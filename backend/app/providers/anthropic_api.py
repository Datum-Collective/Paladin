"""Anthropic Messages API adapter (raw HTTPS, documented wire format).

Deliberately omitted on every request, because current models reject them: temperature, top_p, top_k, assistant
prefill, and forced tool_choice. Reasoning depth is steered with output_config.effort."""
import json

from .. import keys
from .base import Provider, ProviderError, retry_after, sse_lines

TRANSPORT = None  # tests inject an httpx transport
API_VERSION = "2023-06-01"


def classify(status: int, body, headers) -> ProviderError:
    err = (body or {}).get("error") or {}
    etype = err.get("type", "")
    msg = err.get("message") or f"Anthropic returned HTTP {status}."
    rid = headers.get("request-id") or (body or {}).get("request_id")
    code = err.get("error_code") or (body or {}).get("error_code") or ""
    ra = retry_after(headers)
    common = dict(status=status, request_id=rid)
    if status == 401 or etype == "authentication_error":
        return ProviderError("auth", msg, **common)
    if status == 402 or etype == "billing_error":
        return ProviderError("quota", msg, **common)
    if status == 403 or etype == "permission_error":
        return ProviderError("permission", msg, **common)
    if status == 404 or etype == "not_found_error":
        return ProviderError("not_found", msg, **common)
    if status == 413 or etype == "request_too_large":
        return ProviderError("too_large", msg, **common)
    if status == 429 or etype == "rate_limit_error":
        if code == "enforced_spend_limit_reached" or "spend limit" in msg.lower():
            return ProviderError("quota", msg, **common)   # resets monthly; retrying cannot help
        return ProviderError("rate_limit", msg, retryable=True, retry_after=ra, **common)
    if status == 529 or etype == "overloaded_error":
        return ProviderError("overloaded", msg, retryable=True, retry_after=ra, **common)
    if status >= 500 or etype in ("api_error", "timeout_error"):
        return ProviderError("server", msg, retryable=True, retry_after=ra, **common)
    return ProviderError("invalid", msg, **common)


class Anthropic(Provider):
    id = "anthropic"
    name = "Claude"
    base_url = "https://api.anthropic.com"

    def _transport(self): return TRANSPORT
    def _has_key(self): return keys.configured("anthropic")
    def _models_path(self): return "/v1/models?limit=1000"

    def _headers(self):
        return {"x-api-key": keys.get("ANTHROPIC_API_KEY") or "", "anthropic-version": API_VERSION,
                "content-type": "application/json"}

    def _classify(self, status, body, headers): return classify(status, body, headers)

    def _parse_models(self, data):
        out = []
        for m in data.get("data", []):
            if m.get("lifecycle") in ("retired", "deprecated_removed"):
                continue
            caps = m.get("capabilities") or {}
            out.append({"id": m["id"], "name": m.get("display_name") or m["id"],
                        "max_output": m.get("max_tokens"), "context": m.get("max_input_tokens"),
                        "retires_at": m.get("retires_at"), "deprecated": bool(m.get("deprecated_at")),
                        "effort": bool((caps.get("effort") or {}).get("supported", "effort" in caps))})
        return out

    def _request(self, model, system, messages, effort, max_tokens):
        payload = {"model": model, "max_tokens": max_tokens, "stream": True,
                   "messages": [{"role": m["role"], "content": m["content"]} for m in messages]}
        if system:
            payload["system"] = system
        if effort:
            payload["output_config"] = {"effort": effort}
        return "/v1/messages", payload

    async def _stream_events(self, resp):
        usage = {"input": 0, "output": 0}
        stop = "end_turn"
        async for name, d in sse_lines(resp):
            t = d.get("type", name)
            if t == "message_start":
                usage["input"] = ((d.get("message") or {}).get("usage") or {}).get("input_tokens", 0)
            elif t == "content_block_delta":
                delta = d.get("delta") or {}
                if delta.get("type") == "text_delta":
                    yield {"type": "text", "delta": delta.get("text", "")}
            elif t == "message_delta":
                stop = (d.get("delta") or {}).get("stop_reason") or stop
                usage["output"] = (d.get("usage") or {}).get("output_tokens", usage["output"])
            elif t == "error":
                e = classify(200, {"error": d.get("error") or {}}, {})
                e.status = None
                yield e.to_event()
                return
            elif t == "message_stop":
                yield {"type": "done", "stop_reason": stop, "usage": usage}
                return
        # the stream closed without message_stop: report it, never present a cut-off answer as complete
        yield ProviderError("network", "The response ended early.", retryable=True).to_event()
