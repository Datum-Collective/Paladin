"""Accounts, httpOnly session cookies, per-source API keys, login rate limit."""
import hashlib
import os
import re
import secrets
import time
from collections import defaultdict, deque

import bcrypt
from fastapi import HTTPException, Request

from . import store, workspaces

COOKIE = "apc_session"
SESSION_TTL = 7 * 86400
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}$")
_fails: dict[str, deque] = defaultdict(deque)
FAIL_LIMIT, FAIL_WINDOW = 5, 300


def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt()).decode()


def check_pw(pw: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode()[:72], h.encode())
    except ValueError:
        return False


def register(email: str, pw: str) -> int:
    email = email.strip().lower()
    if not EMAIL.match(email):
        raise HTTPException(422, "invalid email")
    if not 8 <= len(pw) <= 128:
        raise HTTPException(422, "password must be 8-128 chars")
    if store.q("SELECT 1 FROM users WHERE email=?", (email,)):
        raise HTTPException(409, "account exists")
    return store.run("INSERT INTO users(email,pw) VALUES(?,?)", (email, hash_pw(pw)))


def seed_demo() -> None:
    u, p = os.environ.get("DEMO_USER"), os.environ.get("DEMO_PASSWORD")
    if u and p and not store.q("SELECT 1 FROM users WHERE email=?", (u.lower(),)):
        store.run("INSERT INTO users(email,pw) VALUES(?,?)", (u.lower(), hash_pw(p)))


def _throttled(key: str) -> bool:
    now = time.time()
    d = _fails[key]
    while d and d[0] < now - FAIL_WINDOW:
        d.popleft()
    return len(d) >= FAIL_LIMIT


def login(email: str, pw: str, ip: str) -> str:
    key = f"{ip}|{email.strip().lower()}"
    if _throttled(key):
        raise HTTPException(429, "too many attempts, try later")
    rows = store.q("SELECT id,pw FROM users WHERE email=?", (email.strip().lower(),))
    if not rows or not check_pw(pw, rows[0]["pw"]):
        _fails[key].append(time.time())
        raise HTTPException(401, "invalid credentials")
    tok = secrets.token_urlsafe(32)
    store.run("INSERT INTO sessions(token,user_id,created) VALUES(?,?,?)", (tok, rows[0]["id"], time.time()))
    return tok


LOCAL_EMAIL = "local@paladin.local"


def desktop_mode() -> bool:
    return os.environ.get("DESKTOP_MODE") == "1"


def local_login(token: str) -> str:
    """Desktop only: the Electron main process proves itself with a per-launch token and gets the one local
    account. No password exists for it that anyone could know; the token never leaves the main process."""
    expected = os.environ.get("APC_DESKTOP_TOKEN", "")
    if not expected or not secrets.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(403, "desktop token required")
    store.run("INSERT OR IGNORE INTO users(email,pw) VALUES(?,?)", (LOCAL_EMAIL, hash_pw(secrets.token_urlsafe(32))))
    uid = store.q("SELECT id FROM users WHERE email=?", (LOCAL_EMAIL,))[0]["id"]
    tok = secrets.token_urlsafe(32)
    store.run("INSERT INTO sessions(token,user_id,created) VALUES(?,?,?)", (tok, uid, time.time()))
    return tok


def logout(tok: str | None) -> None:
    if tok:
        store.run("DELETE FROM sessions WHERE token=?", (tok,))


def _scope(user_id: int, email: str, req: Request | None = None) -> dict:
    """The caller's identity AND the workspace every endpoint operates on. `id` is the workspace id (what all data
    is keyed by); `user_id` is the account. A request names its workspace with X-Workspace (or ?ws= for streams)
    so a second window cannot redirect this one; without it, the account's active workspace is used."""
    ws = workspaces.active(user_id)
    if req is not None:
        raw = req.headers.get("x-workspace") or req.query_params.get("ws") or ""
        if raw.isdigit() and workspaces.owns(user_id, int(raw)):
            ws = int(raw)
    return {"id": ws, "user_id": user_id, "email": email}


def user_from_request(req: Request) -> dict | None:
    tok = req.cookies.get(COOKIE)
    if tok:
        r = store.q("SELECT u.id,u.email,s.created FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?",
                    (tok,))
        if r and time.time() - r[0]["created"] < SESSION_TTL:
            return _scope(r[0]["id"], r[0]["email"], req)
    return None


def require_user(req: Request) -> dict:
    u = user_from_request(req)
    if not u:
        raise HTTPException(401, "authentication required")
    return u


def user_or_key(req: Request) -> dict:
    """Session cookie or X-API-Key; both resolve to a workspace (= user id)."""
    u = user_from_request(req)
    if u:
        return u
    k = req.headers.get("x-api-key")
    if k:
        r = store.q("SELECT u.id,u.email,a.ws FROM api_keys a JOIN users u ON u.id=a.user_id WHERE a.hash=?",
                    (hashlib.sha256(k.encode()).hexdigest(),))
        if r:
            sc = _scope(r[0]["id"], r[0]["email"])
            # a key ingests into the workspace it was created in; older keys (no binding) use the account's first
            bound = r[0]["ws"] if r[0]["ws"] and workspaces.owns(r[0]["id"], r[0]["ws"]) else workspaces.oldest(r[0]["id"])
            if bound:
                sc["id"] = bound
            return sc
    raise HTTPException(401, "authentication required")


def create_key(user_id: int, label: str, ws: int | None = None) -> str:
    key = "apc_" + secrets.token_urlsafe(24)
    store.run("INSERT INTO api_keys(hash,user_id,label,created,ws) VALUES(?,?,?,?,?)",
              (hashlib.sha256(key.encode()).hexdigest(), user_id, label[:64], time.time(), ws))
    return key
