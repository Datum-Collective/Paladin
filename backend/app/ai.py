"""Optional AI drafting and review. Off unless the signed-in user (or the server) has a provider key; never in the
decision path.

Uses Claude when an Anthropic key is present, otherwise OpenAI. The model only rewrites structured facts we computed.
Any failure returns None and the deterministic template is used.
"""
import hashlib
import json
import logging
import os
import re
import time

import httpx

from . import keys

log = logging.getLogger("apc.ai")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/responses"
ANTHROPIC_DEFAULT = "claude-haiku-5-5"
SYSTEM = ("You write remediation runbooks for security engineers. Use ONLY the JSON facts provided. "
          "Do not invent hosts, accounts, commands or findings. Be concise: numbered steps, then a one-line "
          "verification step. Plain text, no markdown headings.")

_models: dict[str, tuple[float, str]] = {}   # sha256(key)[:16] -> (when, model id)
_MODEL_TTL = 600
_CHAT = re.compile(r"^(gpt-|o\d|chatgpt-)")
_NOT_CHAT = ("embedding", "tts", "whisper", "audio", "realtime", "image", "moderation", "transcribe", "dall-e",
             "instruct", "search-preview", "computer-use", "davinci", "babbage")


def provider() -> str | None:
    if keys.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if keys.get("OPENAI_API_KEY"):
        return "openai"
    return None


def enabled() -> bool:
    return provider() is not None


def _cached(key: str) -> str | None:
    hit = _models.get(hashlib.sha256(key.encode()).hexdigest()[:16])
    return hit[1] if hit and time.time() - hit[0] < _MODEL_TTL else None


def _remember(key: str, model: str) -> str:
    _models[hashlib.sha256(key.encode()).hexdigest()[:16]] = (time.time(), model)
    return model


def _anthropic_headers(key: str) -> dict:
    return {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}


def _openai_headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "content-type": "application/json"}


def _pick_openai_model(key: str) -> str | None:
    """The newest small chat model this key can use; the Models API has no capability flags, so this is a filter."""
    if os.environ.get("AI_MODEL_OPENAI"):
        return os.environ["AI_MODEL_OPENAI"]
    got = _cached(key)
    if got:
        return got
    r = httpx.get("https://api.openai.com/v1/models", headers=_openai_headers(key), timeout=20)
    r.raise_for_status()
    ms = [m for m in r.json().get("data", [])
          if _CHAT.match(m.get("id", "")) and not any(x in m["id"] for x in _NOT_CHAT)]
    ms.sort(key=lambda m: ("mini" not in m["id"], -m.get("created", 0)))
    return _remember(key, ms[0]["id"]) if ms else None


def _pick_anthropic_model(key: str) -> str:
    return os.environ.get("AI_MODEL") or _cached(key) or ANTHROPIC_DEFAULT


def _anthropic(key: str, system: str, user: str, max_tokens: int, timeout: float) -> str | None:
    model = _pick_anthropic_model(key)
    body = {"model": model, "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": user}]}
    r = httpx.post(ANTHROPIC_URL, headers=_anthropic_headers(key), json=body, timeout=timeout)
    if r.status_code == 404 and not os.environ.get("AI_MODEL"):
        # the default id is not available to this key: use the cheapest model it can list
        lm = httpx.get("https://api.anthropic.com/v1/models?limit=100", headers=_anthropic_headers(key), timeout=20)
        lm.raise_for_status()
        ids = [m["id"] for m in lm.json().get("data", [])]
        ids.sort(key=lambda i: ("haiku" not in i, i))
        if not ids:
            return None
        body["model"] = _remember(key, ids[0])
        r = httpx.post(ANTHROPIC_URL, headers=_anthropic_headers(key), json=body, timeout=timeout)
    r.raise_for_status()
    return "".join(p.get("text", "") for p in r.json().get("content", []) if p.get("type") == "text")


def _openai(key: str, system: str, user: str, max_tokens: int, timeout: float) -> str | None:
    model = _pick_openai_model(key)
    if not model:
        return None
    # max_output_tokens counts reasoning tokens too, so a small cap can end with no visible text
    body = {"model": model, "instructions": system, "input": user, "store": False,
            "max_output_tokens": max(max_tokens, 4000)}
    r = httpx.post(OPENAI_URL, headers=_openai_headers(key), json=body, timeout=timeout)
    r.raise_for_status()
    out = []
    for item in r.json().get("output", []):
        if item.get("type") == "message":
            out += [c.get("text", "") for c in item.get("content", []) if c.get("type") == "output_text"]
    return "".join(out)


def complete(system: str, user: str, max_tokens: int = 1500, timeout: float = 40) -> str | None:
    """Single-turn call with the user's key. Returns None when disabled or on any failure (logged, key never)."""
    which = provider()
    if not which:
        return None
    user = user[:24000]
    try:
        if which == "anthropic":
            text = _anthropic(keys.get("ANTHROPIC_API_KEY"), system, user, max_tokens, timeout)
        else:
            text = _openai(keys.get("OPENAI_API_KEY"), system, user, max_tokens, timeout)
        return text or None
    except httpx.HTTPStatusError as e:
        log.warning("AI call to %s failed: HTTP %s", which, e.response.status_code)
    except Exception as e:
        log.warning("AI call to %s failed: %s", which, type(e).__name__)
    return None


def draft(facts: dict) -> str | None:
    text = complete(SYSTEM, json.dumps(facts)[:6000], 700, timeout=20)
    return text.strip()[:4000] if text else None
