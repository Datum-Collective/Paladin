"""Common provider contract: one normalised event stream, one error type, shared retry policy.

Events yielded by Provider.stream():
  {"type": "text", "delta": str}
  {"type": "done", "stop_reason": "end_turn"|"max_tokens"|"refusal"|..., "usage": {"input", "output"}, "request_id"}
  {"type": "error", "kind", "message", "hint", "retryable", "status", "request_id"}
"""
import asyncio
import json
import random
from typing import AsyncIterator

import httpx

BACKOFF = (1.0, 2.5, 6.0)      # seconds before retry 1..3 (jitter added); tests override
MAX_RETRY_AFTER = 20.0
CONNECT_TIMEOUT = 15.0
READ_TIMEOUT = 600.0

_GUIDANCE = {
    "auth": "Check the API key in Settings. It may be mistyped, revoked, or for a different organization.",
    "permission": "This key is not allowed to use that model or workspace. Pick another model or use a different key.",
    "quota": "The account has no remaining credit or has hit its spend limit. Add credit or raise the limit with the provider.",
    "rate_limit": "Too many requests right now. Wait a moment and try again.",
    "overloaded": "The provider is overloaded. Try again in a minute.",
    "server": "The provider had an internal error. Try again shortly.",
    "invalid": "The provider rejected the request. Choose a different model or shorten the conversation.",
    "not_found": "That model is not available to this key. Pick another model from the list.",
    "too_large": "The conversation is too large. Start a new one.",
    "network": "Could not reach the provider. Check your internet connection.",
    "unconfigured": "Add an API key for this provider in Settings.",
}


def guidance(kind: str) -> str:
    return _GUIDANCE.get(kind, "Something went wrong. Try again.")


class ProviderError(Exception):
    def __init__(self, kind: str, message: str, *, status: int | None = None, retryable: bool = False,
                 request_id: str | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.kind, self.message, self.status = kind, message, status
        self.retryable, self.request_id, self.retry_after = retryable, request_id, retry_after

    def to_event(self) -> dict:
        return {"type": "error", "kind": self.kind, "message": self.message, "hint": guidance(self.kind),
                "retryable": self.retryable, "status": self.status, "request_id": self.request_id}


def _retry_after(headers) -> float | None:
    try:
        v = float(headers.get("retry-after", ""))
        return max(0.0, min(v, MAX_RETRY_AFTER))
    except (TypeError, ValueError):
        return None


def retry_after(headers) -> float | None:
    return _retry_after(headers)


async def _sleep_for(attempt: int, err: ProviderError) -> None:
    base = BACKOFF[min(attempt, len(BACKOFF) - 1)]
    delay = max(base, err.retry_after or 0.0)
    await asyncio.sleep(delay + (random.random() * 0.25 * delay if delay else 0))


def network_error(exc: Exception) -> ProviderError:
    return ProviderError("network", f"Network error: {type(exc).__name__}", retryable=True)


class Provider:
    id = ""
    name = ""
    base_url = ""
    TRANSPORT_ATTR = "TRANSPORT"

    # --- implemented by adapters ---
    def _headers(self) -> dict: raise NotImplementedError
    def _classify(self, status: int, body, headers) -> ProviderError: raise NotImplementedError
    def _models_path(self) -> str: raise NotImplementedError
    def _parse_models(self, data: dict) -> list[dict]: raise NotImplementedError
    def _request(self, model: str, system: str, messages: list[dict], effort: str | None, max_tokens: int):
        raise NotImplementedError
    def _transport(self): raise NotImplementedError
    def _has_key(self) -> bool: raise NotImplementedError

    async def _stream_events(self, resp: httpx.Response) -> AsyncIterator[dict]:
        raise NotImplementedError
        yield {}

    # --- shared behaviour ---
    def _client(self, timeout=None) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, transport=self._transport(),
                                 timeout=timeout or httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT))

    def _need_key(self) -> None:
        if not self._has_key():
            raise ProviderError("auth", f"No {self.name} API key is set. Add one in Settings.", status=401)

    async def _error_from(self, resp: httpx.Response) -> ProviderError:
        raw = await resp.aread()
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {}
        return self._classify(resp.status_code, body, resp.headers)

    async def list_models(self) -> list[dict]:
        self._need_key()
        err: ProviderError | None = None
        for attempt in range(len(BACKOFF) + 1):
            try:
                async with self._client(httpx.Timeout(30.0, connect=CONNECT_TIMEOUT)) as c:
                    r = await c.get(self._models_path(), headers=self._headers())
                    try:
                        body = r.json() if r.content else {}
                    except ValueError:  # proxy or captive-portal HTML
                        body = {}
                    if r.status_code == 200 and isinstance(body, dict) and "data" in body:
                        return self._parse_models(body)
                    err = self._classify(r.status_code if r.status_code != 200 else 502, body, r.headers)
            except httpx.HTTPError as e:
                err = network_error(e)
            if not err.retryable or attempt >= len(BACKOFF):
                raise err
            await _sleep_for(attempt, err)
        raise err  # pragma: no cover

    async def validate(self) -> dict:
        """A 200 from the models list proves the key authenticates; it does not prove billing allows inference."""
        try:
            models = await self.list_models()
            return {"ok": True, "models": len(models)}
        except ProviderError as e:
            return {"ok": False, "error": e.to_event()}

    async def stream(self, *, model: str, system: str, messages: list[dict], effort: str | None = None,
                     max_tokens: int = 4096) -> AsyncIterator[dict]:
        """Yield normalised events. Retries only before the first byte of a successful response; once streaming
        has started, a failure is reported, not replayed (a replay would duplicate or contradict shown text)."""
        try:
            self._need_key()
        except ProviderError as e:
            yield e.to_event()
            return
        path, payload = self._request(model, system, messages, effort, max_tokens)
        started = False   # once any event reached the caller, a replay would duplicate or contradict shown text
        for attempt in range(len(BACKOFF) + 1):
            err: ProviderError | None = None
            try:
                async with self._client() as c:
                    async with c.stream("POST", path, headers=self._headers(), json=payload) as resp:
                        if resp.status_code != 200:
                            err = await self._error_from(resp)
                        else:
                            rid = resp.headers.get("request-id") or resp.headers.get("x-request-id")
                            async for ev in self._stream_events(resp):
                                if ev.get("type") in ("done", "error"):
                                    ev.setdefault("request_id", rid)
                                started = True
                                yield ev
                            return
            except httpx.HTTPError as e:
                err = network_error(e)
            if err is None:  # pragma: no cover
                return
            if started or not err.retryable or attempt >= len(BACKOFF):
                yield err.to_event()
                return
            await _sleep_for(attempt, err)


async def sse_lines(resp: httpx.Response) -> AsyncIterator[tuple[str | None, dict]]:
    """Parse text/event-stream into (event_name, json_data). Ignores comments, pings with no data, bad JSON."""
    name: str | None = None
    data: list[str] = []
    async for line in resp.aiter_lines():
        if line == "":
            if data:
                try:
                    yield name, json.loads("\n".join(data))
                except ValueError:
                    pass
            name, data = None, []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        try:
            yield name, json.loads("\n".join(data))
        except ValueError:
            pass
