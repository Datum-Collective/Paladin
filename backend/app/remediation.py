"""Remediation lifecycle: proposed -> approved -> executed -> verified (or failed / rolled_back).

Deciding WHAT to cut is analyze.py (deterministic). This module records, approves, executes through a
connector, and verifies against later events. Every transition is audited.
"""
import json
import time

from . import ai, codescan, engine, inventory, store
from .correlate import matches
from .narrate import mitigation_name, technique

STATES = ("proposed", "approved", "executed", "verified", "failed", "rolled_back")
NEXT = {"proposed": {"approved"}, "approved": {"executed"}, "executed": {"verified", "failed", "rolled_back"},
        "verified": {"rolled_back"}, "failed": {"rolled_back"}, "rolled_back": set()}

STEPS = {
    "M1032": ["Enforce multi-factor authentication for the affected account(s) and remote access paths.",
              "Revoke active sessions and re-enrol the second factor."],
    "M1027": ["Rotate the exposed credential and enforce the password policy (length, uniqueness).",
              "Remove credentials from files, scripts and shell history on the source host."],
    "M1026": ["Remove standing admin rights; use just-in-time privileged access.",
              "Audit members of privileged groups and remove unused ones."],
    "M1050": ["Place the exposed application behind exploit protection (WAF / patched build).",
              "Block the scanner source at the edge."],
    "M1038": ["Block interactive shells for the service account (nologin, restricted sudoers).",
              "Apply execution allow-listing on the host."],
    "M1030": ["Restrict RDP/SMB between the DMZ and server VLANs to jump hosts only."],
    "M1022": ["Tighten ACLs on the data share to named groups; remove inherited broad access."],
    "M1017": ["Run targeted phishing awareness training; add mail filtering rules for the lure."],
}


_ensured_for = None


def _ensure() -> None:
    global _ensured_for
    c = store.conn()
    if _ensured_for is c:
        return
    store.run("""CREATE TABLE IF NOT EXISTS remediations(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ws INTEGER NOT NULL, edges TEXT NOT NULL, state TEXT NOT NULL,
        title TEXT NOT NULL, runbook TEXT NOT NULL, ai_drafted INTEGER NOT NULL DEFAULT 0,
        connector TEXT NOT NULL, mark INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '',
        created REAL NOT NULL, updated REAL NOT NULL)""")
    have = {r["name"] for r in store.q("PRAGMA table_info(remediations)")}
    for col, typ in (("risk_before", "REAL"), ("risk_after", "REAL"), ("paths_before", "INTEGER"),
                     ("paths_after", "INTEGER")):
        if col not in have:
            store.run(f"ALTER TABLE remediations ADD COLUMN {col} {typ}")
    store.run("""CREATE TABLE IF NOT EXISTS audit(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ws INTEGER NOT NULL, rem INTEGER NOT NULL, actor TEXT NOT NULL,
        action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', ts REAL NOT NULL)""")
    _ensured_for = c


def _audit(ws: int, rem: int, actor: str, action: str, detail: str = "") -> None:
    store.run("INSERT INTO audit(ws,rem,actor,action,detail,ts) VALUES(?,?,?,?,?,?)",
              (ws, rem, actor, action, detail[:500], time.time()))


def _row(r) -> dict:
    d = dict(r)
    d["edges"] = json.loads(d["edges"])
    d["ai_drafted"] = bool(d["ai_drafted"])
    return d


def _facts(ws: int, edge_ids: list[str]) -> dict:
    snap = engine.snapshot(ws)
    by_id = {e.id: e for e in snap["edges"]}
    out = []
    for eid in edge_ids:
        e = by_id[eid]
        t = technique(e.technique)
        out.append({"edge": eid, "from": e.src, "to": e.dst, "technique": e.technique, "technique_name": t["name"],
                    "mitigation": e.mitigation, "mitigation_name": mitigation_name(e.mitigation),
                    "observed": e.observed, "evidence_event_ids": e.evidence[:5], "cost": e.cost})
    return {"steps_to_close": out, "risk_now": round(snap["risk"], 3)}


def template_runbook(facts: dict) -> str:
    lines = []
    for i, s in enumerate(facts["steps_to_close"], 1):
        lines.append(f"{i}. Close {s['from']} -> {s['to']} ({s['technique']} {s['technique_name']})"
                     f"{' [observed: ' + ', '.join(s['evidence_event_ids']) + ']' if s['observed'] else ''}")
        for st in STEPS.get(s["mitigation"], [f"Apply mitigation {s['mitigation']} {s['mitigation_name']}."]):
            lines.append(f"   - {st}")
    lines.append("Verify: new events must stop matching these steps; risk should fall after re-analysis.")
    return "\n".join(lines)


def propose(ws: int, actor: str, edge_ids: list[str], title: str) -> dict:
    _ensure()
    valid = {e.id for e in inventory.load()["edges"]} | {e["id"] for e in codescan.load_model(ws)["edges"]}
    if not edge_ids or any(e not in valid for e in edge_ids):
        raise ValueError("unknown edge id")
    facts = _facts(ws, edge_ids)
    text = ai.draft(facts)
    runbook, used_ai = (text, True) if text else (template_runbook(facts), False)
    now = time.time()
    rid = store.run(
        "INSERT INTO remediations(ws,edges,state,title,runbook,ai_drafted,connector,created,updated) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (ws, json.dumps(sorted(set(edge_ids))), "proposed", title[:120], runbook, int(used_ai), "model", now, now))
    _audit(ws, rid, actor, "proposed", ",".join(edge_ids))
    return get(ws, rid)


def get(ws: int, rid: int) -> dict:
    _ensure()
    r = store.q("SELECT * FROM remediations WHERE id=? AND ws=?", (rid, ws))
    if not r:
        raise KeyError(rid)
    return _row(r[0])


def list_(ws: int) -> list[dict]:
    _ensure()
    return [_row(r) for r in store.q("SELECT * FROM remediations WHERE ws=? ORDER BY id DESC", (ws,))]


def audit_log(ws: int, rid: int) -> list[dict]:
    _ensure()
    return [dict(r) for r in store.q("SELECT actor,action,detail,ts FROM audit WHERE ws=? AND rem=? ORDER BY id",
                                     (ws, rid))]


def _set(ws: int, rid: int, state: str, actor: str, detail: str = "", **cols) -> dict:
    cur = get(ws, rid)
    if state not in NEXT[cur["state"]]:
        raise ValueError(f"cannot go from {cur['state']} to {state}")
    sets = ["state=?", "updated=?"] + [f"{k}=?" for k in cols]
    store.run(f"UPDATE remediations SET {','.join(sets)} WHERE id=? AND ws=?",
              (state, time.time(), *cols.values(), rid, ws))
    _audit(ws, rid, actor, state, detail)
    return get(ws, rid)


def approve(ws: int, rid: int, actor: str) -> dict:
    return _set(ws, rid, "approved", actor)


def execute(ws: int, rid: int, actor: str) -> dict:
    """Model connector: closes the edges in the analysed environment. This is NOT a change to real hosts;
    a real connector would replace this call and the state machine stays the same."""
    cur = get(ws, rid)
    if cur["state"] != "approved":
        raise ValueError(f"cannot go from {cur['state']} to executed")
    def live(snap):  # paths an analyst would act on
        return sum(1 for p in snap["paths"] if p["severity"] in ("CRITICAL", "HIGH", "MEDIUM"))

    b = engine.snapshot(ws)
    store.apply_fix(ws, cur["edges"])
    a = engine.snapshot(ws)
    return _set(ws, rid, "executed", actor,
                f"connector={cur['connector']} risk {b['risk']:.3f}->{a['risk']:.3f} paths {live(b)}->{live(a)}",
                mark=store.event_count(ws), risk_before=round(b["risk"], 4), risk_after=round(a["risk"], 4),
                paths_before=live(b), paths_after=live(a))


def verify(ws: int, rid: int, actor: str) -> dict:
    """Verified only if (a) the edges are closed in the graph and (b) no event ingested AFTER execution still
    matches any of them. Otherwise failed, with the offending event ids as the note."""
    cur = get(ws, rid)
    if cur["state"] != "executed":
        raise ValueError(f"cannot go from {cur['state']} to verified")
    from .models import Edge
    inv = {e.id: e for e in inventory.load()["edges"]}
    inv.update({e["id"]: Edge(**e) for e in codescan.load_model(ws)["edges"]})
    later = store.get_events(ws)[cur["mark"]:]
    still = [ev.id for ev in later for eid in cur["edges"] if matches(inv[eid], ev)]
    closed = set(cur["edges"]) <= store.applied_fixes(ws)
    if closed and not still:
        return _set(ws, rid, "verified", actor, "no matching events since execution")
    why = f"still observed after fix: {','.join(sorted(set(still))[:10])}" if still else "edges not closed"
    return _set(ws, rid, "failed", actor, why, note=why)


def rollback(ws: int, rid: int, actor: str) -> dict:
    cur = get(ws, rid)
    out = _set(ws, rid, "rolled_back", actor)
    keep = set()
    for other in list_(ws):
        if other["id"] != rid and other["state"] in ("executed", "verified"):
            keep |= set(other["edges"])
    for e in set(cur["edges"]) - keep:
        store.run("DELETE FROM fixes WHERE ws=? AND edge=?", (ws, e))
    return out
