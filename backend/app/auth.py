"""Sign-in with GitHub through Supabase Auth, run server-side with PKCE; sessions in httpOnly cookies.

Web:     GET /api/auth/login -> Supabase -> GitHub (account picker) -> GET /api/auth/callback sets the cookies.
Desktop: Electron's main process starts the login (POST /api/auth/desktop/start, with its per-launch token) and
         opens it in the system browser. The callback parks the new session in memory; the app window collects it
         with POST /api/auth/desktop/claim, which only the main process can authorise. The browser tab never gets
         the session, and a web page cannot start or finish a desktop sign-in.

The browser JS never sees a token. Every request's access token is verified here (JWKS, or HS256 for legacy
projects) and then handed to supa.py, so all data access runs as this user under row-level security.
"""
import asyncio
import base64
import hashlib
import html
import logging
import os
import secrets
import time
import uuid

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import config, keys, supa, workspaces
from .http import client
from .ratelimit import RateLimit

ACCESS_COOKIE = "sb_access"
REFRESH_COOKIE = "sb_refresh"
VERIFIER_COOKIE = "pkce_verifier"
DESKTOP_COOKIE = "desktop_signin"
REFRESH_MAX_AGE = 60 * 60 * 24 * 30
# Tolerated clock drift between this machine and Supabase. Without it, a fresh token's `iat` can sit in our
# future and PyJWT rejects it (ImmatureSignatureError) for a few seconds.
CLOCK_LEEWAY_S = 60
# Refresh the session when the access token has less than this left, so a scan started now keeps a valid
# session for its whole run (scan threads cannot refresh: that would rotate the browser's refresh token).
REFRESH_MARGIN_S = 15 * 60
DESKTOP_SIGNIN_TTL_S = 600
API_KEY_PREFIX = "apc_"

log = logging.getLogger("uvicorn.error")
router = APIRouter(tags=["auth"])
_login_limit = RateLimit(limit=20, window_s=60)
_jwks_client: jwt.PyJWKClient | None = None
# Many requests arrive at once after a token expires; one refresh serves them all (Supabase rotates refresh
# tokens and treats reuse outside a short window as theft, revoking the session).
_refreshes: dict[str, tuple[float, dict | None]] = {}
_refresh_locks: dict[str, asyncio.Lock] = {}
# desktop sign-ins in progress: nonce -> {"created": t, "session": None | supabase session}
_desktop: dict[str, dict] = {}


def desktop_mode() -> bool:
    return config.desktop_mode()


# ---------- cookies ----------
def _cookie(resp: Response, name: str, value: str, max_age: int, path: str = "/"):
    resp.set_cookie(name, value, max_age=max_age, httponly=True, secure=config.secure_cookies(),
                    samesite="lax", path=path)


def _set_session(resp: Response, session: dict):
    _cookie(resp, ACCESS_COOKIE, session["access_token"], int(session.get("expires_in") or 3600))
    _cookie(resp, REFRESH_COOKIE, session["refresh_token"], REFRESH_MAX_AGE)


def _clear_session(resp: Response):
    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        resp.delete_cookie(name, path="/")


# ---------- tokens ----------
def _jwks() -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(f"{config.SUPABASE_URL}/auth/v1/.well-known/jwks.json", cache_keys=True)
    return _jwks_client


def verify(token: str) -> dict:
    """Verified claims of a Supabase access token, or jwt.InvalidTokenError."""
    if config.SUPABASE_JWT_SECRET:
        claims = jwt.decode(token, config.SUPABASE_JWT_SECRET, algorithms=["HS256"], audience="authenticated",
                            leeway=CLOCK_LEEWAY_S)
    else:
        key = _jwks().get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["ES256", "RS256"], audience="authenticated",
                            leeway=CLOCK_LEEWAY_S)
    if not claims.get("sub") or claims.get("role") not in (None, "authenticated"):
        raise jwt.InvalidTokenError("not a user session")
    return claims


def _expires_soon(token: str) -> bool:
    """Only decides WHEN to refresh; the token is fully verified before it is trusted for anything."""
    try:
        exp = jwt.decode(token, options={"verify_signature": False}).get("exp", 0)
    except jwt.InvalidTokenError:
        return True
    return exp - time.time() < REFRESH_MARGIN_S


async def _refresh(refresh_token: str) -> dict | None:
    key = hashlib.sha256(refresh_token.encode()).hexdigest()
    lock = _refresh_locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _refreshes.get(key)
        if hit and time.monotonic() - hit[0] < 30:
            return hit[1]
        try:
            r = await client.post(f"{config.SUPABASE_URL}/auth/v1/token?grant_type=refresh_token",
                                  headers={"apikey": config.SUPABASE_ANON_KEY}, json={"refresh_token": refresh_token})
        except httpx.HTTPError as e:
            log.warning("Session refresh failed: could not reach Supabase: %r", e)
            return None
        session = r.json() if r.status_code == 200 else None
        if session is None:
            log.warning("Session refresh rejected: status=%s", r.status_code)
        _refreshes[key] = (time.monotonic(), session)
        for k in [k for k, (t, _) in _refreshes.items() if time.monotonic() - t > 60]:
            _refreshes.pop(k, None)
            _refresh_locks.pop(k, None)
        return session


def _replace_cookie(request: Request, name: str, value: str) -> None:
    """Make the rest of this request see the refreshed token, as if the browser had sent it."""
    jar = dict(request.cookies)
    jar[name] = value
    header = "; ".join(f"{k}={v}" for k, v in jar.items()).encode("latin-1")
    request.scope["headers"] = [(k, v) for k, v in request.scope["headers"] if k != b"cookie"] + [(b"cookie", header)]


async def session_middleware(request: Request, call_next):
    """Refresh an expiring session for ANY route (JSON, streams, files), and send the new cookies with whatever
    response the route produces. Doing this in a dependency would lose the cookies on routes that return their own
    Response object, and losing a rotated refresh token logs the user out."""
    path = request.url.path
    access, refresh = request.cookies.get(ACCESS_COOKIE), request.cookies.get(REFRESH_COOKIE)
    session, rejected = None, False
    if (path.startswith("/api/") and not path.startswith("/api/auth/") and refresh and config.SUPABASE_ENABLED
            and (not access or _expires_soon(access))):
        session = await _refresh(refresh)
        if session:
            _replace_cookie(request, ACCESS_COOKIE, session["access_token"])
        else:
            rejected = True
    resp = await call_next(request)
    if session:
        _set_session(resp, session)
    elif rejected:
        _clear_session(resp)
    return resp


def _profile(claims: dict) -> dict:
    meta = claims.get("user_metadata") or {}
    login = str(meta.get("user_name") or meta.get("preferred_username") or "")[:64]
    return {"id": claims["sub"], "login": login, "name": meta.get("full_name") or meta.get("name") or login,
            "avatar_url": meta.get("avatar_url") if str(meta.get("avatar_url", "")).startswith("https://") else None,
            "email": claims.get("email") or None}


def _scope(claims: dict, req: Request | None = None) -> dict:
    """The caller's identity AND the workspace every endpoint operates on. `id` is the workspace id (what all data
    is keyed by); `user_id` is the account. A request names its workspace with X-Workspace (or ?ws= for streams)
    so a second window cannot redirect this one; without it, the account's active workspace is used."""
    uid = claims["sub"]
    ws = None
    if req is not None:
        raw = req.headers.get("x-workspace") or req.query_params.get("ws") or ""
        if raw.isdigit() and len(raw) < 19 and workspaces.owns(uid, int(raw)):
            ws = int(raw)
    if ws is None:
        ws = workspaces.active(uid)
    p = _profile(claims)
    return {"id": ws, "user_id": uid, "email": p["email"], "login": p["login"], "actor": p["login"] or uid,
            "profile": p}


async def current_claims(request: Request) -> dict:
    """Dependency: verified claims of the signed-in user, with supa bound to their token. No workspace lookup."""
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise HTTPException(401, "authentication required")
    try:
        claims = verify(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "session expired") from None
    except (jwt.InvalidTokenError, jwt.PyJWKClientError) as e:
        log.warning("Rejected access token: %s: %s", type(e).__name__, e)
        raise HTTPException(401, "authentication required") from None
    supa.set_user(token, claims["sub"])
    keys.bind(claims["sub"])   # this user's pasted model keys apply to everything this request does
    return claims


async def require_user(request: Request) -> dict:
    claims = await current_claims(request)
    # Supabase calls are blocking; run them off the event loop. to_thread copies the context (the user's token).
    return await asyncio.to_thread(_scope, claims, request)


async def user_or_key(request: Request) -> dict:
    """Session cookie, or an ingest API key (X-API-Key) for log shippers."""
    if request.cookies.get(ACCESS_COOKIE):
        return await require_user(request)
    k = request.headers.get("x-api-key", "")
    if k.startswith(API_KEY_PREFIX) and 8 < len(k) <= 200:
        supa.set_user(None, None)   # the key is checked by the database itself (ingest_with_key)
        return {"api_key": k, "id": None, "user_id": None}
    raise HTTPException(401, "authentication required")


# ---------- web + desktop sign-in ----------
def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _sweep_desktop() -> None:
    now = time.time()
    for k in [k for k, v in _desktop.items() if now - v["created"] > DESKTOP_SIGNIN_TTL_S]:
        _desktop.pop(k, None)


def _require_desktop_token(request: Request) -> None:
    expected = os.environ.get("APC_DESKTOP_TOKEN", "")
    given = request.headers.get("x-desktop-token", "")
    if not expected or not secrets.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(403, "desktop token required")


@router.get("/api/auth/login", dependencies=[Depends(_login_limit)])
def login(desktop: str | None = None):
    if not config.SUPABASE_ENABLED:
        raise HTTPException(503, "sign-in is not configured on this server")
    if desktop_mode():
        # only a sign-in the app itself started (desktop/start, with its per-launch token) may run here
        _sweep_desktop()
        if not desktop or desktop not in _desktop or _desktop[desktop]["session"] is not None:
            return HTMLResponse(_page("This sign-in link has expired", "Start signing in again from the Paladin app."),
                                status_code=404)
    verifier, challenge = _pkce_pair()
    params = httpx.QueryParams(provider="github", redirect_to=f"{config.app_url()}/api/auth/callback",
                               code_challenge=challenge, code_challenge_method="s256",
                               # Supabase forwards this to GitHub: always show the account picker instead of
                               # silently reusing the browser's GitHub session
                               prompt="select_account")
    resp = RedirectResponse(f"{config.SUPABASE_URL}/auth/v1/authorize?{params}", status_code=302)
    _cookie(resp, VERIFIER_COOKIE, verifier, 600, path="/api/auth")
    if desktop_mode():
        _cookie(resp, DESKTOP_COOKIE, desktop, 600, path="/api/auth")
    return resp


def _page(title: str, body: str) -> str:
    return (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            f"<title>{html.escape(title)}</title><body style='font:15px system-ui;max-width:28rem;margin:15vh auto;"
            f"padding:0 16px;text-align:center'><h1 style='font-size:20px'>{html.escape(title)}</h1>"
            f"<p>{html.escape(body)}</p></body>")


def _login_failed(reason: str, **details):
    log.warning("GitHub login failed: %s %s", reason, details)
    if desktop_mode():
        return HTMLResponse(_page("Sign-in failed", "Return to the Paladin app and try again."), status_code=400)
    return RedirectResponse("/?login_error=1", status_code=302)   # fixed target: never a user-supplied URL


@router.get("/api/auth/callback", dependencies=[Depends(_login_limit)])
async def callback(request: Request, code: str | None = None, error: str | None = None,
                   error_code: str | None = None, error_description: str | None = None):
    verifier = request.cookies.get(VERIFIER_COOKIE)
    nonce = request.cookies.get(DESKTOP_COOKIE) if desktop_mode() else None
    if error or error_description:
        return _login_failed("provider returned an error", error=error, error_code=error_code,
                             error_description=error_description)
    if not code:
        return _login_failed("no code in callback URL")
    if not verifier:
        return _login_failed("PKCE verifier cookie missing", cookies=sorted(request.cookies))
    if desktop_mode():
        _sweep_desktop()
        if not nonce or nonce not in _desktop or _desktop[nonce]["session"] is not None:
            return _login_failed("desktop sign-in unknown, expired or already completed")
    try:
        r = await client.post(f"{config.SUPABASE_URL}/auth/v1/token?grant_type=pkce",
                              headers={"apikey": config.SUPABASE_ANON_KEY},
                              json={"auth_code": code, "code_verifier": verifier})
    except httpx.HTTPError as e:
        return _login_failed("could not reach Supabase", error=repr(e))
    if r.status_code != 200:
        return _login_failed("code exchange rejected", status=r.status_code, body=r.text[:300])
    session = r.json()
    try:
        claims = verify(session["access_token"])
    except (jwt.InvalidTokenError, jwt.PyJWKClientError, KeyError) as e:
        return _login_failed("issued token failed verification", error=f"{type(e).__name__}: {e}")
    log.info("Signed in %s (%s)", claims["sub"], _profile(claims)["login"])
    if desktop_mode():
        _desktop[nonce]["session"] = session
        resp = HTMLResponse(_page("You're signed in", "Return to the Paladin app. You can close this tab."))
    else:
        resp = RedirectResponse("/", status_code=302)
        _set_session(resp, session)
    resp.delete_cookie(VERIFIER_COOKIE, path="/api/auth")
    resp.delete_cookie(DESKTOP_COOKIE, path="/api/auth")
    return resp


@router.post("/api/auth/desktop/start")
def desktop_start(request: Request):
    """Main process only: begin a sign-in and get the URL to open in the system browser."""
    if not desktop_mode():
        raise HTTPException(404, "not available")
    _require_desktop_token(request)
    _sweep_desktop()
    if len(_desktop) >= 5:
        _desktop.pop(min(_desktop, key=lambda k: _desktop[k]["created"]))
    nonce = secrets.token_urlsafe(32)
    _desktop[nonce] = {"created": time.time(), "session": None}
    return {"url": f"{config.app_url()}/api/auth/login?{httpx.QueryParams(desktop=nonce)}"}


@router.post("/api/auth/desktop/claim")
def desktop_claim(request: Request, response: Response):
    """The app window collects a completed sign-in. Electron's main process attaches the per-launch token to this
    one request from our own page, so neither a web page nor another local program can claim a session."""
    if not desktop_mode():
        raise HTTPException(404, "not available")
    _require_desktop_token(request)
    _sweep_desktop()
    done = [k for k, v in _desktop.items() if v["session"] is not None]
    if not done:
        return {"signed_in": False}
    session = _desktop.pop(done[-1])["session"]
    _set_session(response, session)
    return {"signed_in": True}


@router.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    if token := request.cookies.get(ACCESS_COOKIE):
        try:   # this session only: signing out of the web app must not sign the desktop app out
            await client.post(f"{config.SUPABASE_URL}/auth/v1/logout?scope=local",
                              headers={"apikey": config.SUPABASE_ANON_KEY, "Authorization": f"Bearer {token}"})
        except httpx.HTTPError:
            pass   # still clear local cookies
    _clear_session(response)
    supa.set_user(None, None)
    return {"ok": True}


@router.get("/api/me")
async def me(claims: dict = Depends(current_claims)):
    return _profile(claims)


# ---------- ingest API keys ----------
class KeyBody(BaseModel):
    label: str = Field(default="source", min_length=1, max_length=64)


def _key_row(r: dict) -> dict:
    return {"id": r["id"], "label": r.get("label") or r.get("source") or "source", "key_prefix": r["key_prefix"],
            "ws": r.get("ws"), "created_at": r["created_at"], "revoked_at": r.get("revoked_at")}


def create_key(user_id: str, label: str, ws: int | None = None) -> str:
    raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
    supa.insert("api_keys", {"user_id": user_id, "label": label[:64], "ws": ws, "key_prefix": raw[:10],
                             "key_hash": hashlib.sha256(raw.encode()).hexdigest()}, returning="id")
    return raw   # returned exactly once; only the hash is stored


@router.get("/api/keys")
def list_keys(u: dict = Depends(require_user)):
    rows = supa.select("api_keys", {"user_id": supa.eq(u["user_id"])},
                       columns="id,label,source,key_prefix,ws,created_at,revoked_at", order="created_at.desc")
    return {"keys": [_key_row(r) for r in rows]}


@router.post("/api/keys")
def make_key(b: KeyBody, u: dict = Depends(require_user)):
    return {"key": create_key(u["user_id"], b.label, u["id"])}


@router.delete("/api/keys/{key_id}")
def revoke_key(key_id: str, u: dict = Depends(require_user)):
    try:
        uuid.UUID(key_id)
    except ValueError:
        raise HTTPException(404, "key not found") from None
    rows = supa.update("api_keys", {"id": supa.eq(key_id), "user_id": supa.eq(u["user_id"]), "revoked_at": "is.null"},
                       {"revoked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, returning="id")
    if not rows:
        raise HTTPException(404, "key not found")
    return {"ok": True}
