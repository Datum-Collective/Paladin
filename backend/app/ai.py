"""Optional AI drafting. Off unless ANTHROPIC_API_KEY is set; never in the decision path.

The model only rewrites structured facts we computed. Any failure returns None and the template is used.
"""
import json
import os

import httpx

from . import keys

URL = "https://api.anthropic.com/v1/messages"
SYSTEM = ("You write remediation runbooks for security engineers. Use ONLY the JSON facts provided. "
          "Do not invent hosts, accounts, commands or findings. Be concise: numbered steps, then a one-line "
          "verification step. Plain text, no markdown headings.")


def enabled() -> bool:
    return bool(keys.get("ANTHROPIC_API_KEY"))


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
    if not enabled():
        return None
    try:
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
