"""Workspaces: a user's named, isolated analysis spaces. Every data table is keyed by workspace id, so switching
the active workspace is what changes what every endpoint sees. Legacy data keyed by user id is adopted as that
user's first workspace (same id), so nothing is migrated or lost."""
import time

from . import harness, store

MAX_PER_USER = 50
NAME_MAX = 60


class WorkspaceError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def kind_of(repo_url: str | None) -> str:
    if not repo_url:
        return "empty"
    return "github" if repo_url.startswith("https://github.com/") else "local"


def _status_map(ids: list[int]) -> dict[int, dict]:
    """Newest scan per workspace in one query, so listing N workspaces is not N+1 lookups."""
    if not ids:
        return {}
    harness.ensure()
    marks = ",".join("?" * len(ids))
    rows = store.q(f"SELECT id,ws,state,error,updated FROM jobs WHERE id IN "
                   f"(SELECT MAX(id) FROM jobs WHERE ws IN ({marks}) GROUP BY ws)", tuple(ids))
    return {r["ws"]: {"job": r["id"], "state": r["state"], "error": r["error"], "updated": r["updated"]} for r in rows}


def _event_counts(ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {r["ws"]: r["c"] for r in store.q(f"SELECT ws, COUNT(*) c FROM events WHERE ws IN ({marks}) GROUP BY ws", tuple(ids))}


def _rows(rows) -> list[dict]:
    ids = [r["id"] for r in rows]
    st, ev = _status_map(ids), _event_counts(ids)
    return [{"id": r["id"], "name": r["name"], "repo_url": r["repo_url"], "kind": kind_of(r["repo_url"]),
             "created": r["created"], "opened": r["opened"], "events": ev.get(r["id"], 0), "status": st.get(r["id"])}
            for r in rows]


def _row(r) -> dict:
    return _rows([r])[0]


def _next_id() -> int:
    a = store.q("SELECT COALESCE(MAX(id),0) m FROM workspaces")[0]["m"]
    b = store.q("SELECT COALESCE(MAX(id),0) m FROM users")[0]["m"]
    return max(a, b) + 1


def _owned(user_id: int, ws: int):
    r = store.q("SELECT * FROM workspaces WHERE id=? AND owner=?", (ws, user_id))
    if not r:
        raise WorkspaceError(404, "workspace not found")
    return r[0]


def clean_name(name: str) -> str:
    n = " ".join((name or "").split())
    if not n:
        raise WorkspaceError(422, "Give the workspace a name.")
    if len(n) > NAME_MAX or any(ord(c) < 32 for c in n):
        raise WorkspaceError(422, f"Names can be up to {NAME_MAX} characters.")
    return n


def _unique(user_id: int, name: str, exclude: int | None = None) -> bool:
    rows = store.q("SELECT id FROM workspaces WHERE owner=? AND lower(name)=lower(?)", (user_id, name))
    return not [r for r in rows if r["id"] != exclude]


def _insert(user_id: int, name: str, repo_url: str | None, ws_id: int | None = None) -> int:
    now = time.time()
    wid = ws_id or _next_id()
    store.run("INSERT INTO workspaces(id,owner,name,repo_url,created,opened) VALUES(?,?,?,?,?,?)",
              (wid, user_id, name, repo_url, now, now))
    return wid


def ensure_default(user_id: int) -> int:
    with store.lock():   # a page load fires many requests at once; check-then-insert must be one step
        rows = store.q("SELECT id FROM workspaces WHERE owner=? ORDER BY opened DESC", (user_id,))
        if rows:
            return rows[0]["id"]
        taken = store.q("SELECT 1 FROM workspaces WHERE id=?", (user_id,))
        return _insert(user_id, "Workspace", None, None if taken else user_id)


def active(user_id: int) -> int:
    r = store.q("SELECT ws FROM active_ws WHERE user_id=?", (user_id,))
    if r and store.q("SELECT 1 FROM workspaces WHERE id=? AND owner=?", (r[0]["ws"], user_id)):
        return r[0]["ws"]
    ws = ensure_default(user_id)
    _set_active(user_id, ws)
    return ws


def _set_active(user_id: int, ws: int) -> None:
    store.run("INSERT INTO active_ws(user_id,ws) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET ws=excluded.ws", (user_id, ws))
    store.run("UPDATE workspaces SET opened=? WHERE id=?", (time.time(), ws))


def listing(user_id: int) -> dict:
    act = active(user_id)
    rows = store.q("SELECT * FROM workspaces WHERE owner=? ORDER BY opened DESC, id DESC", (user_id,))
    return {"active": act, "workspaces": _rows(rows)}


def find_by_repo(user_id: int, repo_url: str):
    # GitHub names are case-insensitive; filesystem paths are matched exactly
    r = store.q("SELECT * FROM workspaces WHERE owner=? AND (repo_url=? OR "
                "(repo_url LIKE 'https://github.com/%' AND lower(repo_url)=lower(?)))", (user_id, repo_url, repo_url))
    return r[0] if r else None


def create(user_id: int, name: str | None, repo_url: str | None = None) -> dict:
    with store.lock():
        return _create(user_id, name, repo_url)


def _create(user_id: int, name: str | None, repo_url: str | None) -> dict:
    ensure_default(user_id)
    if store.q("SELECT COUNT(*) c FROM workspaces WHERE owner=?", (user_id,))[0]["c"] >= MAX_PER_USER:
        raise WorkspaceError(409, f"You can have up to {MAX_PER_USER} workspaces. Delete one first.")
    if name is None or not name.strip():
        base, n, name = "Workspace", 1, "Workspace"
        while not _unique(user_id, name):
            n += 1
            name = f"{base} {n}"
    else:
        name = clean_name(name)
        if not _unique(user_id, name):
            raise WorkspaceError(409, "A workspace with that name already exists.")
    wid = _insert(user_id, name, repo_url)
    _set_active(user_id, wid)
    return _row(_owned(user_id, wid))


def create_for_repo(user_id: int, full_name: str, repo_url: str) -> dict:
    name, n = full_name[:NAME_MAX], 1
    while not _unique(user_id, name):
        n += 1
        name = f"{full_name[:NAME_MAX - 4]} {n}"
    return create(user_id, name, repo_url)


def open_(user_id: int, ws: int) -> dict:
    _owned(user_id, ws)
    _set_active(user_id, ws)
    return listing(user_id)


def rename(user_id: int, ws: int, name: str) -> dict:
    _owned(user_id, ws)
    n = clean_name(name)
    if not _unique(user_id, n, exclude=ws):
        raise WorkspaceError(409, "A workspace with that name already exists.")
    store.run("UPDATE workspaces SET name=? WHERE id=?", (n, ws))
    return _row(_owned(user_id, ws))


def delete(user_id: int, ws: int) -> dict:
    _owned(user_id, ws)
    harness.wipe(ws)
    store.wipe_workspace(ws)
    store.run("DELETE FROM workspaces WHERE id=?", (ws,))
    store.run("DELETE FROM api_keys WHERE user_id=? AND ws=?", (user_id, ws))
    store.run("DELETE FROM active_ws WHERE user_id=? AND ws=?", (user_id, ws))
    return listing(user_id)   # active() falls back to the most recent one, or creates a fresh default


def oldest(user_id: int) -> int | None:
    r = store.q("SELECT id FROM workspaces WHERE owner=? ORDER BY created ASC, id ASC LIMIT 1", (user_id,))
    return r[0]["id"] if r else None


def owns(user_id: int, ws: int) -> bool:
    return bool(store.q("SELECT 1 FROM workspaces WHERE id=? AND owner=?", (ws, user_id)))
