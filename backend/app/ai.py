"""Optional AI drafting. Off unless ANTHROPIC_API_KEY is set; never in the decision path.

The model only rewrites structured facts we computed. Any failure returns None and the template is used.
"""
import json
import os
import random
import time

import httpx

from . import keys

URL = "https://api.anthropic.com/v1/messages"
_models: dict = {}
SYSTEM = ("You write remediation runbooks for security engineers. Use ONLY the JSON facts provided. "
          "Do not invent hosts, accounts, commands or findings. Be concise: numbered steps, then a one-line "
          "verification step. Plain text, no markdown headings.")


def provider() -> str | None:
    if keys.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if keys.get("OPENAI_API_KEY"):
        return "openai"
    return None


def enabled() -> bool:
    return provider() is not None


def draft(facts: dict) -> str | None:
    if not enabled():
        return None
    try:
        r = httpx.post(
            URL,
            headers={"x-api-key": keys.get("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": os.environ.get("AI_MODEL", "claude-haiku-5-5"), "max_tokens": 700, "system": SYSTEM,
                  "messages": [{"role": "user", "content": json.dumps(facts)[:6000]}]},
            timeout=20,
        )
        r.raise_for_status()
        parts = r.json().get("content", [])
        text = "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()
        return text[:4000] or None
    except Exception:
        return None


def complete(system: str, user: str, max_tokens: int = 1500) -> str | None:
    """Generic single-turn call. Returns None when disabled or on any failure."""
    selected = provider()
    if not selected:
        return None
    try:
        if selected == "openai":
            key = keys.get("OPENAI_API_KEY") or ""
            r = httpx.post("https://api.openai.com/v1/responses",
                           headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
                           json={"model": os.environ.get("AI_MODEL_OPENAI", "gpt-5-mini"), "instructions": system,
                                 "input": user[:24000], "store": False, "max_output_tokens": max(max_tokens, 4000)},
                           timeout=40)
            r.raise_for_status()
            return "".join(part.get("text", "") for item in r.json().get("output", [])
                           if item.get("type") == "message" for part in item.get("content", [])
                           if part.get("type") == "output_text") or None
        r = httpx.post(
            URL,
            headers={"x-api-key": keys.get("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": os.environ.get("AI_MODEL", "claude-haiku-5-5"), "max_tokens": max_tokens,
                  "system": system, "messages": [{"role": "user", "content": user[:24000]}]},
            timeout=40,
        )
        r.raise_for_status()
        return "".join(p.get("text", "") for p in r.json().get("content", []) if p.get("type") == "text")
    except Exception:
        return None


RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
MAX_TRIES = 4
BACKOFF = (2.0, 5.0, 12.0)         # seconds before retry 1..3 (tests set this to zeros)
MAX_RETRY_AFTER = 30.0


def model() -> str:
    return os.environ.get("AI_MODEL", "claude-haiku-5-5")


def call(system: str, user: str, max_tokens: int = 1500, cancelled=lambda: False) -> tuple[str | None, str]:
    """One Haiku request with retries. Returns (text, "") or (None, kind) where kind is one of: off, auth, quota,
    rate_limit, overloaded, network, invalid, server, cancelled. Rate limits honour Retry-After; waiting is
    cancellable. Keys never appear in what is returned."""
    if not enabled():
        return None, "off"
    kind = "server"
    for attempt in range(MAX_TRIES):
        if cancelled():
            return None, "cancelled"
        wait = 0.0
        try:
            r = httpx.post(URL, headers={"x-api-key": keys.get("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01",
                                         "content-type": "application/json"},
                           json={"model": model(), "max_tokens": max_tokens, "system": system,
                                 "messages": [{"role": "user", "content": user}]}, timeout=60)
            if r.status_code == 200:
                text = "".join(p.get("text", "") for p in r.json().get("content", []) if p.get("type") == "text")
                return text, ""
            kind = {401: "auth", 403: "auth", 402: "quota", 400: "invalid", 404: "invalid", 429: "rate_limit",
                    529: "overloaded"}.get(r.status_code, "server")
            if r.status_code not in RETRY_STATUS:
                return None, kind
            try:
                wait = min(MAX_RETRY_AFTER, float(r.headers.get("retry-after", "")))
            except ValueError:
                wait = 0.0
        except (httpx.HTTPError, ValueError):
            kind = "network"
        if attempt == MAX_TRIES - 1:
            break
        delay = max(wait, BACKOFF[min(attempt, len(BACKOFF) - 1)]) * (1 + random.random() * 0.2)
        end = time.monotonic() + delay
        while time.monotonic() < end:
            if cancelled():
                return None, "cancelled"
            time.sleep(min(0.25, max(0.0, end - time.monotonic())))
    return None, kind
