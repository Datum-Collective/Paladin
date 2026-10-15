"""OpenAI Responses API adapter (raw HTTPS). store=false so conversations are not retained server-side by default.

The Models API returns no capability flags, so the chat-capable filter below is an app-maintained heuristic over
model ids and must be re-checked against OpenAI's live list when new families ship."""
import logging
import re

from .. import keys
from .base import Provider, ProviderError, retry_after, sse_lines

TRANSPORT = None
_CHAT = re.compile(r"^(gpt-|o\d|chatgpt-)")
_NOT_CHAT = ("embedding", "tts", "whisper", "audio", "realtime", "image", "moderation", "transcribe", "dall-e",
             "instruct", "search-preview", "computer-use", "davinci", "babbage")
_QUOTA = {"insufficient_quota", "credit_balance_exhausted", "organization_spend_limit_exceeded",
          "billing_hard_limit_reached", "billing_not_active"}
_LOG = logging.getLogger(__name__)

# The Responses API emits lifecycle and content events in addition to text deltas. Paladin has no tool loop, so
# those events are intentionally observed and ignored; terminal events and user-visible text are handled below.
_PROGRESS_EVENTS = {
    "response.created", "response.queued", "response.in_progress",
    "response.output_item.added", "response.output_item.done",
    "response.content_part.added", "response.content_part.done",
    "response.output_text.done", "response.refusal.done",
    "response.reasoning_summary_part.added", "response.reasoning_summary_part.done",
    "response.reasoning_summary_text.delta", "response.reasoning_summary_text.done",
    "response.function_call_arguments.delta", "response.function_call_arguments.done",
}


def classify(status: int, body, headers) -> ProviderError:
    err = (body or {}).get("error") or {}
    code, etype = err.get("code") or "", err.get("type") or ""
    msg = err.get("message") or f"OpenAI returned HTTP {status}."
    rid = headers.get("x-request-id")
    ra = retry_after(headers)
    common = dict(status=status, request_id=rid)
    if status == 401:
        return ProviderError("auth", msg, **common)
    if status == 403:
        return ProviderError("permission", msg, **common)
    if status == 404 or code == "model_not_found":
        return ProviderError("not_found", msg, **common)
    if status == 413:
        return ProviderError("too_large", msg, **common)
    if status == 429:
        if code in _QUOTA or etype in _QUOTA:   # 429 is overloaded: branch on the code, never retry quota
            return ProviderError("quota", msg, **common)
        return ProviderError("rate_limit", msg, retryable=True, retry_after=ra, **common)
    if status >= 500:
        return ProviderError("server", msg, retryable=True, retry_after=ra, **common)
    return ProviderError("invalid", msg, **common)


def _is_chat_model(m: dict) -> bool:
    i = m.get("id", "")
    return bool(_CHAT.match(i)) and not any(x in i for x in _NOT_CHAT) and not m.get("shutdown_date")


class OpenAI(Provider):
    id = "openai"
    name = "OpenAI"
    base_url = "https://api.openai.com"

    def _transport(self): return TRANSPORT
    def _has_key(self): return keys.configured("openai")
    def _models_path(self): return "/v1/models"

    def _headers(self):
        return {"Authorization": f"Bearer {keys.get('OPENAI_API_KEY') or ''}", "content-type": "application/json"}

    def _classify(self, status, body, headers): return classify(status, body, headers)

    def _parse_models(self, data):
        ms = [m for m in data.get("data", []) if _is_chat_model(m)]
        ms.sort(key=lambda m: m.get("created", 0), reverse=True)
        return [{"id": m["id"], "name": m["id"], "max_output": None, "context": None, "retires_at": None,
                 "deprecated": False, "effort": bool(re.match(r"^(o\d|gpt-5|gpt-6)", m["id"]))} for m in ms]

    def _request(self, model, system, messages, effort, max_tokens):
        # max_output_tokens counts reasoning tokens too; a small cap can end with no visible text
        payload = {"model": model, "stream": True, "store": False, "max_output_tokens": max(max_tokens, 4000),
                   "input": [{"role": m["role"], "content": m["content"]} for m in messages]}
        if system:
            payload["instructions"] = system
        if effort:
            payload["reasoning"] = {"effort": effort}
        return "/v1/responses", payload

    @staticmethod
    def _usage(resp: dict) -> dict:
        u = (resp or {}).get("usage") or {}
        return {"input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0)}

    async def _stream_events(self, resp):
        async for _name, d in sse_lines(resp):
            t = d.get("type", "")
            _LOG.debug("OpenAI Responses stream event: %s", t or "<missing>")
            if t == "response.output_text.delta":
                yield {"type": "text", "delta": d.get("delta", "")}
            elif t == "response.refusal.delta":
                yield {"type": "text", "delta": d.get("delta", "")}
            elif t in _PROGRESS_EVENTS:
                continue
            elif t == "response.completed":
                r = d.get("response") or {}
                yield {"type": "done", "stop_reason": "end_turn", "usage": self._usage(r)}
                return
            elif t == "response.incomplete":
                r = d.get("response") or {}
                why = (r.get("incomplete_details") or {}).get("reason", "")
                yield {"type": "done", "stop_reason": "max_tokens" if "max" in why else (why or "incomplete"),
                       "usage": self._usage(r)}
                return
            elif t in ("response.failed", "error"):
                e = (d.get("response") or {}).get("error") or d.get("error") or d
                code = e.get("code") or ""
                kind = "quota" if code in _QUOTA else "rate_limit" if code == "rate_limit_exceeded" else "server"
                yield ProviderError(kind, e.get("message") or "The response failed.",
                                    retryable=kind in ("rate_limit", "server")).to_event()
                return
        yield ProviderError("network", "The response ended early.", retryable=True).to_event()
