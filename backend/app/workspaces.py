"""Workspaces: a user's named, isolated analysis spaces. Every data table is keyed by workspace id, so switching
the active workspace is what changes what every endpoint sees. Rows live in Supabase under row-level security, so
these queries only ever see the signed-in user's workspaces; filtering by user_id here as well is the second layer."""
import threading
import time
from collections import defaultdict

from . import harness, supa

MAX_PER_USER = 50
NAME_MAX = 60
_user_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)


class WorkspaceError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def kind_of(repo_url: str | None) -> str:
    if not repo_url:
        return "empty"
    return "github" if repo_url.startswith("https://github.com/") else "local"


def _status_map(ids: list[int]) -> dict[int, dict]:
    """Newest scan per workspace in one round trip, so listing N workspaces is not N+1 lookups."""
    if not ids:
        return {}
    rows = supa.rpc("workspace_latest_jobs", {"p_ws": ids}) or []
    return {r["ws"]: {"job": r["id"], "state": harness.effective_state(r), "error": r["error"],
                      "updated": r["updated"]} for r in rows}


def _event_counts(ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    return {r["ws"]: r["n"] for r in supa.rpc("workspace_event_counts", {"p_ws": ids}) or []}


def _rows(rows) -> list[dict]:
    ids = [r["id"] for r in rows]
    st, ev = _status_map(ids), _event_counts(ids)
    return [{"id": r["id"], "name": r["name"], "repo_url": r["repo_url"], "kind": kind_of(r["repo_url"]),
             "created": r["created"], "opened": r["opened"], "events": ev.get(r["id"], 0), "status": st.get(r["id"])}
            for r in rows]


def _row(r) -> dict:
    return _rows([r])[0]


def _owned(user_id: str, ws: int):
    r = supa.first("workspaces", {"id": supa.eq(int(ws)), "user_id": supa.eq(user_id)})
    if not r:
        raise WorkspaceError(404, "workspace not found")
    return r


def clean_name(name: str) -> str:
    n = " ".join((name or "").split())
    if not n:
        raise WorkspaceError(422, "Give the workspace a name.")
    if len(n) > NAME_MAX or any(ord(c) < 32 for c in n):
        raise WorkspaceError(422, f"Names can be up to {NAME_MAX} characters.")
    return n


def _all(user_id: str, order: str = "opened.desc,id.desc") -> list[dict]:
    return supa.select("workspaces", {"user_id": supa.eq(user_id)}, order=order)


def _unique(user_id: str, name: str, exclude: int | None = None, rows: list[dict] | None = None) -> bool:
    rows = _all(user_id) if rows is None else rows
    return not [r for r in rows if r["name"].lower() == name.lower() and r["id"] != exclude]


def _insert(user_id: str, name: str, repo_url: str | None) -> int:
    now = time.time()
    try:
        row = supa.insert("workspaces", {"user_id": user_id, "name": name, "repo_url": repo_url,
                                         "created": now, "opened": now}, returning="id")[0]
    except supa.DataError as e:
        if e.status == 409 and "limit" in e.message:
            raise WorkspaceError(409, f"You can have up to {MAX_PER_USER} workspaces. Delete one first.") from None
        if e.status == 409:
            raise WorkspaceError(409, "A workspace with that name already exists.") from None
        raise
    return row["id"]


def ensure_default(user_id: str) -> int:
    with _user_locks[user_id]:   # a page load fires many requests at once; check-then-insert must be one step
        rows = supa.select("workspaces", {"user_id": supa.eq(user_id)}, columns="id", order="opened.desc", limit=1)
        if rows:
            return rows[0]["id"]
        return _insert(user_id, "Workspace", None)


def active(user_id: str) -> int:
    r = supa.first("active_ws", {"user_id": supa.eq(user_id)}, columns="ws")
    if r and owns(user_id, r["ws"]):
        return r["ws"]
    ws = ensure_default(user_id)
    _set_active(user_id, ws)
    return ws


def _set_active(user_id: str, ws: int) -> None:
    supa.upsert("active_ws", {"user_id": user_id, "ws": ws}, "user_id")
    supa.update("workspaces", {"id": supa.eq(ws), "user_id": supa.eq(user_id)}, {"opened": time.time()},
                returning=None)


def listing(user_id: str) -> dict:
    act = active(user_id)
    return {"active": act, "workspaces": _rows(_all(user_id))}


def find_by_repo(user_id: str, repo_url: str):
    # GitHub names are case-insensitive; filesystem paths are matched exactly
    for r in _all(user_id):
        u = r["repo_url"] or ""
        if u == repo_url or (u.startswith("https://github.com/") and u.lower() == repo_url.lower()):
            return r
    return None


def create(user_id: str, name: str | None, repo_url: str | None = None) -> dict:
    with _user_locks[user_id]:
        return _create(user_id, name, repo_url)


def _create(user_id: str, name: str | None, repo_url: str | None) -> dict:
    rows = _all(user_id)
    if not rows:
        _insert(user_id, "Workspace", None)
        rows = _all(user_id)
    if len(rows) >= MAX_PER_USER:
        raise WorkspaceError(409, f"You can have up to {MAX_PER_USER} workspaces. Delete one first.")
    if name is None or not name.strip():
        base, n, name = "Workspace", 1, "Workspace"
        while not _unique(user_id, name, rows=rows):
            n += 1
            name = f"{base} {n}"
    else:
        name = clean_name(name)
        if not _unique(user_id, name, rows=rows):
            raise WorkspaceError(409, "A workspace with that name already exists.")
    wid = _insert(user_id, name, repo_url)
    _set_active(user_id, wid)
    return _row(_owned(user_id, wid))


def create_for_repo(user_id: str, full_name: str, repo_url: str) -> dict:
    rows = _all(user_id)
    name, n = full_name[:NAME_MAX], 1
    while not _unique(user_id, name, rows=rows):
        n += 1
        name = f"{full_name[:NAME_MAX - 4]} {n}"
    return create(user_id, name, repo_url)


def open_(user_id: str, ws: int) -> dict:
    _owned(user_id, ws)
    _set_active(user_id, ws)
    return listing(user_id)


def rename(user_id: str, ws: int, name: str) -> dict:
    _owned(user_id, ws)
    n = clean_name(name)
    if not _unique(user_id, n, exclude=ws):
        raise WorkspaceError(409, "A workspace with that name already exists.")
    try:
        supa.update("workspaces", {"id": supa.eq(ws), "user_id": supa.eq(user_id)}, {"name": n}, returning=None)
    except supa.DataError as e:
        if e.status == 409:
            raise WorkspaceError(409, "A workspace with that name already exists.") from None
        raise
    return _row(_owned(user_id, ws))


def delete(user_id: str, ws: int) -> dict:
    _owned(user_id, ws)
    harness.wipe(ws)
    # Every table references workspaces with ON DELETE CASCADE: events, scans, fixes, keys and the active pointer go too
    supa.delete("workspaces", {"id": supa.eq(ws), "user_id": supa.eq(user_id)})
    from . import store
    store.invalidate(ws)
    return listing(user_id)   # active() falls back to the most recent one, or creates a fresh default


def oldest(user_id: str) -> int | None:
    r = supa.first("workspaces", {"user_id": supa.eq(user_id)}, columns="id", order="created.asc,id.asc")
    return r["id"] if r else None


def owns(user_id: str, ws: int) -> bool:
    return bool(supa.first("workspaces", {"id": supa.eq(int(ws)), "user_id": supa.eq(user_id)}, columns="id"))
