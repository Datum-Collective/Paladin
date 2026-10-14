"""Workspace data in Supabase (see supa.py: every call runs as the signed-in user, under RLS).

Events are append-only; every row is scoped to a workspace. The analysis engine re-reads a workspace's events on
every graph request and the live stream polls for changes, so events are cached in memory per (user, workspace)
and refreshed incrementally: one cheap count request when nothing changed, only the new rows when something did.
The cache is keyed by user as well as workspace, so it can never serve one user's rows to another.
"""
import threading
import time

from pydantic import ValidationError

from . import supa
from .models import Event

MAX_EVENTS = 50_000
CHUNK = 500
COUNT_TTL = 1.0   # the live stream polls twice a second; one count per second per workspace is plenty

_lock = threading.RLock()
_events: dict[tuple[str, int], dict] = {}          # (user, ws) -> {"count", "max_seq", "events"}
_counts: dict[tuple[str, int], tuple[float, int]] = {}
_fixes: dict[tuple[str, int], tuple[float, set]] = {}


def _key(ws: int) -> tuple[str, int]:
    return (supa.user_id() or "", int(ws))


def invalidate(ws: int) -> None:
    """Forget cached data for a workspace (any user: a key ingest has no user context)."""
    with _lock:
        for cache in (_events, _counts, _fixes):
            for k in [k for k in cache if k[1] == int(ws)]:
                cache.pop(k, None)


def reset_connection() -> None:
    """Drop all cached data (tests, sign-out)."""
    with _lock:
        _events.clear()
        _counts.clear()
        _fixes.clear()


def lock() -> threading.RLock:
    return _lock


# ---- events ----
def event_count(ws: int) -> int:
    k = _key(ws)
    hit = _counts.get(k)
    if hit and time.monotonic() - hit[0] < COUNT_TTL:
        return hit[1]
    n = supa.count("events", {"ws": supa.eq(ws)})
    _counts[k] = (time.monotonic(), n)
    return n


def _to_event(row: dict) -> Event | None:
    try:
        return Event(**{**row["data"], "id": f"e{row['seq']}"})
    except (ValidationError, TypeError, KeyError):
        return None   # a row written directly through the API that is not a valid event: skip it


def _fetch_after(ws: int, after: int) -> list[dict]:
    rows: list[dict] = []
    while True:
        page = supa.select("events", {"ws": supa.eq(ws), "seq": supa.gt(after)}, columns="seq,data",
                           order="seq.asc", limit=supa.PAGE)
        rows.extend(page)
        if len(page) < supa.PAGE:
            return rows
        after = page[-1]["seq"]


def get_events(ws: int) -> list[Event]:
    k = _key(ws)
    n = supa.count("events", {"ws": supa.eq(ws)})
    with _lock:
        cached = _events.get(k)
    if cached and cached["count"] == n:
        return cached["events"]
    if cached and n > cached["count"]:
        new = _fetch_after(ws, cached["max_seq"])
        if cached["count"] + len(new) == n:     # pure append since last read
            evs = cached["events"] + [e for e in map(_to_event, new) if e]
            entry = {"count": n, "max_seq": new[-1]["seq"] if new else cached["max_seq"], "events": evs}
            with _lock:
                _events[k] = entry
            return evs
    rows = _fetch_after(ws, 0)                  # first read, or rows were deleted: reload
    evs = [e for e in map(_to_event, rows) if e]
    with _lock:
        _events[k] = {"count": len(rows), "max_seq": rows[-1]["seq"] if rows else 0, "events": evs}
        _counts[k] = (time.monotonic(), len(rows))
    return evs


def add_events(ws: int, events: list[Event]) -> int:
    """Append events (capped per workspace). Returns how many were stored."""
    room = max(0, MAX_EVENTS - supa.count("events", {"ws": supa.eq(ws)}))
    batch = events[:room]
    uid = supa.user_id()
    for i in range(0, len(batch), CHUNK):
        supa.insert("events", [{"ws": ws, "user_id": uid, "data": e.model_dump(exclude={"id"})}
                               for e in batch[i:i + CHUNK]], returning=None)
    invalidate(ws)
    return len(batch)


def ingest_with_key(key: str, events: list[Event]) -> dict:
    """Log shipper path: no session, only an API key. The database checks the key and picks its workspace."""
    out = supa.rpc("ingest_with_key", {"p_key": key, "p_events": [e.model_dump(exclude={"id"}) for e in events]})
    if out and out.get("ws") is not None:
        invalidate(out["ws"])
    return out or {"accepted": 0}


# ---- applied fixes ----
def applied_fixes(ws: int) -> set[str]:
    k = _key(ws)
    hit = _fixes.get(k)
    if hit and time.monotonic() - hit[0] < COUNT_TTL:
        return set(hit[1])
    out = {r["edge"] for r in supa.select("fixes", {"ws": supa.eq(ws)}, columns="edge")}
    _fixes[k] = (time.monotonic(), out)
    return set(out)


def apply_fix(ws: int, edges: list[str]) -> None:
    if edges:
        supa.insert_ignore("fixes", [{"ws": ws, "edge": e, "user_id": supa.user_id()} for e in edges], "ws,edge")
    invalidate(ws)


def remove_fixes(ws: int, edges: list[str]) -> None:
    if edges:
        supa.delete("fixes", {"ws": supa.eq(ws), "edge": supa.in_(edges)})
    invalidate(ws)


# ---- simulation position ----
def sim_pos(ws: int) -> int:
    r = supa.first("sim", {"ws": supa.eq(ws)}, columns="pos")
    return r["pos"] if r else 0


def set_sim_pos(ws: int, pos: int) -> None:
    supa.upsert("sim", {"ws": ws, "pos": pos, "user_id": supa.user_id()}, "ws")


# ---- wiping ----
def reset_workspace(ws: int) -> None:
    for t in ("events", "fixes", "sim"):
        supa.delete(t, {"ws": supa.eq(ws)})
    invalidate(ws)


def wipe_workspace(ws: int) -> None:
    """Remove every trace of a workspace's analysis data (not the workspace itself)."""
    for t in ("events", "fixes", "sim", "remediations", "audit", "code_models", "jobs"):
        supa.delete(t, {"ws": supa.eq(ws)})
    invalidate(ws)
