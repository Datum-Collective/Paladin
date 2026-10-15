"""Supabase data access AS THE SIGNED-IN USER.

Every call carries the user's own access token, so Postgres row-level security decides what it can see and change
(supabase/migrations/0003_app_data.sql). Nothing here holds the service key: the same code runs in the desktop app.

The token is per request: auth.require_user puts it in a context variable, which FastAPI's worker threads and
scan threads (started with a copied context) inherit. Without a token, calls go out as the anonymous role and RLS
returns nothing, so a missing token fails closed.
"""
import contextvars
import json as _json
import threading

import httpx

from . import config

TRANSPORT: httpx.BaseTransport | None = None   # tests inject a fake Supabase
_token: contextvars.ContextVar[str | None] = contextvars.ContextVar("supabase_access_token", default=None)
_uid: contextvars.ContextVar[str | None] = contextvars.ContextVar("supabase_user_id", default=None)
_client: httpx.Client | None = None
_client_lock = threading.Lock()
PAGE = 1000   # Supabase's default max rows per response


class DataError(Exception):
    """A Supabase request failed. `status` is what the API should answer; `message` is safe to show."""

    def __init__(self, status: int, message: str, code: str = ""):
        super().__init__(message)
        self.status, self.message, self.code = status, message, code


def set_user(token: str | None, user_id: str | None) -> None:
    _token.set(token)
    _uid.set(user_id)


def user_id() -> str | None:
    return _uid.get()


def client() -> httpx.Client:
    global _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(transport=TRANSPORT, timeout=httpx.Timeout(20.0))
        return _client


def reset_client() -> None:
    global _client
    with _client_lock:
        if _client is not None:
            _client.close()
        _client = None


def _error(r: httpx.Response) -> DataError:
    try:
        body = r.json()
    except ValueError:
        body = {}
    code = str(body.get("code", "")) if isinstance(body, dict) else ""
    msg = str(body.get("message", "")) if isinstance(body, dict) else ""
    if code == "23505":
        return DataError(409, "That already exists.", code)
    if code == "23514" or "limit reached" in msg:
        # check constraints and the row caps in 0003 (their messages are ours, not Postgres internals)
        return DataError(409, msg if "limit" in msg else "That value is not allowed.", code)
    # PostgREST returns PGRST205 while its schema cache cannot find a table.
    # That most commonly means a deployment skipped one of our numbered SQL
    # migrations (for example 0004, which creates Assistant conversations).
    # Treat it as a recoverable service configuration issue rather than asking
    # a signed-in user to retry an invalid request.
    if code == "PGRST205" or "does not exist" in msg.lower():
        return DataError(503, "The database schema is incomplete. Apply the Supabase migrations, then retry.", code)
    if code in ("42501", "PGRST301", "PGRST302") or r.status_code in (401, 403):
        return DataError(401 if r.status_code == 401 else 404, "Not found or not signed in.", code)
    if code == "23503":
        return DataError(404, "Not found.", code)
    if r.status_code >= 500:
        return DataError(503, "The database is unavailable. Try again shortly.", code)
    return DataError(400, "The database rejected the request.", code)


def request(method: str, path: str, *, params: dict | None = None, json=None, prefer: str | None = None,
            headers: dict | None = None) -> httpx.Response:
    if not config.SUPABASE_ENABLED:
        raise DataError(503, "Supabase is not configured on this server.")
    tok = _token.get()
    h = {"apikey": config.SUPABASE_ANON_KEY, "Authorization": f"Bearer {tok or config.SUPABASE_ANON_KEY}"}
    if prefer:
        h["Prefer"] = prefer
    if headers:
        h.update(headers)
    try:
        r = client().request(method, f"{config.SUPABASE_URL}/rest/v1/{path}", params=params,
                             content=None if json is None else _json.dumps(json, default=str),
                             headers={**h, **({"Content-Type": "application/json"} if json is not None else {})})
    except httpx.HTTPError as e:
        raise DataError(503, "Could not reach the database. Check your connection.") from e
    if r.status_code >= 400:
        raise _error(r)
    return r


# ---- filters ----
def eq(v) -> str:
    return f"eq.{_lit(v)}"


def neq(v) -> str:
    return f"neq.{_lit(v)}"


def gt(v) -> str:
    return f"gt.{_lit(v)}"


def lt(v) -> str:
    return f"lt.{_lit(v)}"


def in_(values) -> str:
    return "in.(" + ",".join(_quote(v) for v in values) + ")"


def _lit(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _quote(v) -> str:
    s = _lit(v)
    # PostgREST list syntax: quote anything with reserved characters
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"' if any(c in s for c in ',()" \\') else s


# ---- table access ----
def select(table: str, filters: dict | None = None, *, columns: str = "*", order: str | None = None,
           limit: int | None = None, offset: int | None = None) -> list[dict]:
    params = {"select": columns, **(filters or {})}
    if order:
        params["order"] = order
    if limit is not None:
        params["limit"] = str(limit)
    if offset:
        params["offset"] = str(offset)
    return request("GET", table, params=params).json()


def first(table: str, filters: dict, *, columns: str = "*", order: str | None = None) -> dict | None:
    rows = select(table, filters, columns=columns, order=order, limit=1)
    return rows[0] if rows else None


def count(table: str, filters: dict | None = None) -> int:
    r = request("HEAD", table, params={"select": "*", **(filters or {})}, prefer="count=exact")
    total = r.headers.get("content-range", "*/0").rsplit("/", 1)[-1]
    return int(total) if total.isdigit() else 0


def insert(table: str, rows: dict | list[dict], *, returning: str | None = "*") -> list[dict]:
    params = {"select": returning} if returning else None
    r = request("POST", table, params=params, json=rows,
                prefer="return=representation" if returning else "return=minimal")
    return r.json() if returning else []


def upsert(table: str, rows: dict | list[dict], on_conflict: str, *, returning: str | None = None) -> list[dict]:
    params = {"on_conflict": on_conflict, **({"select": returning} if returning else {})}
    prefer = "resolution=merge-duplicates," + ("return=representation" if returning else "return=minimal")
    r = request("POST", table, params=params, json=rows, prefer=prefer)
    return r.json() if returning else []


def insert_ignore(table: str, rows: dict | list[dict], on_conflict: str) -> None:
    request("POST", table, params={"on_conflict": on_conflict}, json=rows,
            prefer="resolution=ignore-duplicates,return=minimal")


def update(table: str, filters: dict, values: dict, *, returning: str | None = "*") -> list[dict]:
    if not filters:
        raise ValueError("refusing an unfiltered update")
    params = {**filters, **({"select": returning} if returning else {})}
    r = request("PATCH", table, params=params, json=values,
                prefer="return=representation" if returning else "return=minimal")
    return r.json() if returning else []


def delete(table: str, filters: dict, *, returning: str | None = None) -> list[dict]:
    if not filters:
        raise ValueError("refusing an unfiltered delete")
    params = {**filters, **({"select": returning} if returning else {})}
    r = request("DELETE", table, params=params, prefer="return=representation" if returning else "return=minimal")
    return r.json() if returning else []


def rpc(fn: str, args: dict):
    return request("POST", f"rpc/{fn}", json=args).json()
