"""Provider credentials. Held in process memory only: the Electron main process pushes them after it decrypts them
from the OS keychain, and nothing here ever writes them to disk or returns them over HTTP. Web deployments fall
back to server environment variables."""
import contextvars
import os
import re
import threading

NAMES = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "github": "GITHUB_TOKEN"}
_VALID = re.compile(r"\S{1,512}")
_mem: dict[str, str] = {}

# Web: a signed-in user may paste their own model key. It lives in this process's memory only, under their user id,
# is never written to disk or returned over HTTP, and is only ever used for that user's requests and jobs.
WEB_PROVIDERS = ("anthropic", "openai")
_MAX_USERS = 2000
_user: contextvars.ContextVar[str | None] = contextvars.ContextVar("apc_key_user", default=None)
_by_user: dict[str, dict[str, str]] = {}
_lock = threading.Lock()


def bind(user_id: str | None) -> None:
    """Called once the request is authenticated. Threads started with Context.run (harness jobs) inherit it."""
    _user.set(user_id)


def get(env_name: str) -> str | None:
    if env_name == "GITHUB_TOKEN" and os.environ.get("DESKTOP_MODE") != "1":
        # A server-wide GitHub token would let every signed-in user reach whatever that token can see. On the web,
        # repo access is per user through the GitHub App (github_access.py); this token is desktop-only.
        return None
    uid = _user.get()
    if uid:
        mine = _by_user.get(uid, {}).get(env_name)
        if mine:
            return mine
    return _mem.get(env_name) or os.environ.get(env_name) or None


def set_user_key(user_id: str, provider: str, value: str | None) -> str | None:
    """Store (or clear, with None) one provider key for a user. Returns the previous value so a failed check can
    put it back."""
    if provider not in WEB_PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    if value is not None and not (isinstance(value, str) and _VALID.fullmatch(value)):
        raise ValueError(f"invalid key value for {provider}")
    name = NAMES[provider]
    with _lock:
        mine = _by_user.get(user_id)
        prev = (mine or {}).get(name)
        if value is None:
            if mine is not None:
                mine.pop(name, None)
                if not mine:
                    del _by_user[user_id]
        else:
            if mine is None:
                if len(_by_user) >= _MAX_USERS:
                    _by_user.pop(next(iter(_by_user)))   # oldest entry out; that user simply pastes again
                mine = _by_user[user_id] = {}
            mine[name] = value
        return prev


def user_has(user_id: str | None, provider: str) -> bool:
    return bool(user_id and _by_user.get(user_id, {}).get(NAMES[provider]))


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
    with _lock:
        _by_user.clear()
