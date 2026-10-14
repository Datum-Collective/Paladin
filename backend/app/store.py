"""SQLite store (stdlib). Events are append-only; every row is scoped to a workspace."""
import json
import os
import sqlite3
import threading
from pathlib import Path

from .models import Event

MAX_EVENTS = 50_000
_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, pw TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS api_keys(hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, label TEXT, created REAL);
CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, ws INTEGER NOT NULL, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ev_ws ON events(ws, seq);
CREATE TABLE IF NOT EXISTS fixes(ws INTEGER NOT NULL, edge TEXT NOT NULL, PRIMARY KEY(ws, edge));
CREATE TABLE IF NOT EXISTS sim(ws INTEGER PRIMARY KEY, pos INTEGER NOT NULL);
"""


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        d = Path(os.environ.get("DATA_DIR", "./data_dir"))
        d.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(d / "apc.db", check_same_thread=False, isolation_level=None)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
    return _conn


def reset_connection() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
    _conn = None


def q(sql: str, args: tuple = ()):
    with _lock:
        return conn().execute(sql, args).fetchall()


def run(sql: str, args: tuple = ()) -> int:
    with _lock:
        return conn().execute(sql, args).lastrowid


def event_count(ws: int) -> int:
    return q("SELECT COUNT(*) c FROM events WHERE ws=?", (ws,))[0]["c"]


def add_events(ws: int, events: list[Event]) -> int:
    """Append events; ids are assigned from the sequence. Returns number stored (capped)."""
    with _lock:
        room = max(0, MAX_EVENTS - event_count(ws))
        n = 0
        c = conn()
        c.execute("BEGIN")
        try:
            for ev in events[:room]:
                cur = c.execute("INSERT INTO events(ws,data) VALUES(?,?)", (ws, "{}"))
                ev = ev.model_copy(update={"id": f"e{cur.lastrowid}"})
                c.execute("UPDATE events SET data=? WHERE seq=?", (ev.model_dump_json(), cur.lastrowid))
                n += 1
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
        return n


def get_events(ws: int) -> list[Event]:
    return [Event(**json.loads(r["data"])) for r in q("SELECT data FROM events WHERE ws=? ORDER BY seq", (ws,))]


def applied_fixes(ws: int) -> set[str]:
    return {r["edge"] for r in q("SELECT edge FROM fixes WHERE ws=?", (ws,))}


def apply_fix(ws: int, edges: list[str]) -> None:
    for e in edges:
        run("INSERT OR IGNORE INTO fixes(ws,edge) VALUES(?,?)", (ws, e))


def reset_workspace(ws: int) -> None:
    for t in ("events", "fixes", "sim"):
        run(f"DELETE FROM {t} WHERE ws=?", (ws,))


def sim_pos(ws: int) -> int:
    r = q("SELECT pos FROM sim WHERE ws=?", (ws,))
    return r[0]["pos"] if r else 0


def set_sim_pos(ws: int, pos: int) -> None:
    run("INSERT INTO sim(ws,pos) VALUES(?,?) ON CONFLICT(ws) DO UPDATE SET pos=excluded.pos", (ws, pos))
