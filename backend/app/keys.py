"""Provider credentials. Held in process memory only: the Electron main process pushes them after it decrypts them
from the OS keychain, and nothing here ever writes them to disk or returns them over HTTP. Web deployments fall
back to server environment variables."""
import os
import re

NAMES = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "github": "GITHUB_TOKEN"}
_VALID = re.compile(r"\S{1,512}")
_mem: dict[str, str] = {}


def get(env_name: str) -> str | None:
    if env_name == "GITHUB_TOKEN" and os.environ.get("DESKTOP_MODE") != "1":
        # A server-wide GitHub token would let every signed-in user reach whatever that token can see. On the web,
        # repo access is per user through the GitHub App (github_access.py); this token is desktop-only.
        return None
    return _mem.get(env_name) or os.environ.get(env_name) or None


def configured(provider: str) -> bool:
    return bool(get(NAMES[provider]))


def set_many(patch: dict) -> None:
    """Validate everything first so a bad value never leaves the store half-updated."""
    for provider, value in patch.items():
        if provider not in NAMES:
            raise ValueError(f"unknown provider: {provider}")
        if value is not None and value != "" and not (isinstance(value, str) and _VALID.fullmatch(value)):
            raise ValueError(f"invalid key value for {provider}")
    for provider, value in patch.items():
        if value:
            _mem[NAMES[provider]] = value
        else:
            _mem.pop(NAMES[provider], None)


def status() -> dict[str, bool]:
    return {p: configured(p) for p in NAMES}


def clear() -> None:
    _mem.clear()
