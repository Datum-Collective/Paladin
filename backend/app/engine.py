"""Glue: events + inventory + applied fixes -> graph, ranked paths, fixes (computed, never stored)."""
import time

from . import analyze, codescan, inventory, metrics, store
from .models import Edge, Node
from .correlate import correlate
from .narrate import narrate


def snapshot(ws: int, k: int = 10) -> dict:
    t0 = time.perf_counter()
    inv = inventory.load()
    cm = codescan.load_model(ws)
    all_nodes = inv["nodes"] + [Node(**n) for n in cm["nodes"]]
    all_edges = inv["edges"] + [Edge(**e) for e in cm["edges"]]
    events = store.get_events(ws)
    fixed = store.applied_fixes(ws)
    t1 = time.perf_counter()
    edges = correlate(all_edges, events)
    t2 = time.perf_counter()
    g = analyze.build_graph(all_nodes, edges, removed=fixed)
    t3 = time.perf_counter()
    paths = analyze.top_paths(g, k)
    t4 = time.perf_counter()
    by_id = {e.id: e for e in edges}
    labels = {n.id: n.label for n in all_nodes}
    for p in paths:
        p["narrative"], p["tactics"], p["hops"] = narrate(p, by_id, labels)
    ev_by_id = {e.id: e for e in events}
    nmap = {n.id: n for n in all_nodes}
    for p in paths:
        p["assets"] = [{"id": n, "label": nmap[n].label, "kind": nmap[n].kind,
                        "criticality": nmap[n].criticality} for n in p["nodes"]]
        for h in p["hops"]:
            h["events"] = [{"id": i, "ts": ev_by_id[i].ts, "source": ev_by_id[i].source, "type": ev_by_id[i].type,
                            "actor": ev_by_id[i].actor, "src_ip": ev_by_id[i].src_ip, "raw": ev_by_id[i].raw[:240]}
                           for i in h["evidence"][:3] if i in ev_by_id]
    t5 = time.perf_counter()
    timings = {"load_ms": round((t1 - t0) * 1000, 2), "correlate_ms": round((t2 - t1) * 1000, 2),
               "graph_ms": round((t3 - t2) * 1000, 2), "paths_ms": round((t4 - t3) * 1000, 2),
               "narrate_ms": round((t5 - t4) * 1000, 2), "total_ms": round((t5 - t0) * 1000, 2),
               "events": len(events)}
    metrics.record_snapshot(timings)
    return {
        "nodes": all_nodes, "edges": edges, "fixed": fixed, "graph": g, "paths": paths,
        "risk": analyze.total_risk(paths), "events": len(events), "timings": timings,
    }


def risk_series(ws: int, points: int = 12) -> list[dict]:
    """Risk recomputed on growing prefixes of the event stream (what the analyst would have seen then)."""
    inv = inventory.load()
    cm = codescan.load_model(ws)
    nodes = inv["nodes"] + [Node(**n) for n in cm["nodes"]]
    base = inv["edges"] + [Edge(**e) for e in cm["edges"]]
    events = store.get_events(ws)
    fixed = store.applied_fixes(ws)
    if not events:
        return []
    n = len(events)
    cuts = sorted({max(1, round(n * i / points)) for i in range(1, points + 1)})
    out = []
    for c in cuts:
        g = analyze.build_graph(nodes, correlate(base, events[:c]), removed=fixed)
        ps = analyze.top_paths(g, 10)
        out.append({"events": c, "ts": events[c - 1].ts, "risk": round(analyze.total_risk(ps), 4),
                    "paths": len(ps), "critical": sum(1 for p in ps if p["severity"] == "CRITICAL")})
    return out


def timeline(ws: int, buckets: int = 24) -> dict:
    inv = inventory.load()
    cm = codescan.load_model(ws)
    edges = correlate(inv["edges"] + [Edge(**e) for e in cm["edges"]], store.get_events(ws))
    events = store.get_events(ws)
    if not events:
        return {"buckets": [], "confirmed": [], "events": 0}
    ordered = sorted(events, key=lambda e: e.ts)
    lo, hi = ordered[0].ts, ordered[-1].ts
    from datetime import datetime

    def t(x):
        return datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp()

    span = max(1.0, t(hi) - t(lo))
    rows: dict[int, dict] = {}
    for e in ordered:
        i = min(buckets - 1, int((t(e.ts) - t(lo)) / span * buckets))
        r = rows.setdefault(i, {"index": i, "ts": e.ts, "total": 0, "by_source": {}})
        r["total"] += 1
        r["by_source"][e.source] = r["by_source"].get(e.source, 0) + 1
    by_id = {e.id: e for e in events}
    confirmed = []
    for ed in edges:
        if ed.observed and ed.evidence:
            first = min((by_id[i] for i in ed.evidence if i in by_id), key=lambda x: x.ts)
            confirmed.append({"edge": ed.id, "src": ed.src, "dst": ed.dst, "technique": ed.technique,
                              "first_seen": first.ts, "evidence": ed.evidence[:5], "p": round(ed.p, 3)})
    confirmed.sort(key=lambda c: c["first_seen"])
    return {"buckets": [rows[i] for i in sorted(rows)], "confirmed": confirmed, "events": len(events),
            "range": [lo, hi]}


def compression(snap: dict) -> dict:
    """How much the analyst's reading load shrinks: raw events -> confirmed steps -> ranked paths."""
    confirmed = [e for e in snap["edges"] if e.observed]
    return {"raw_events": snap["events"], "confirmed_steps": len(confirmed),
            "ranked_paths": len(snap["paths"]),
            "critical_or_high": sum(1 for p in snap["paths"] if p["severity"] in ("CRITICAL", "HIGH"))}


def fixes(snap: dict) -> dict:
    g, paths = snap["graph"], snap["paths"]
    return {
        "cheapest_cut": analyze.min_cut_fix(g, paths),
        "best_single": analyze.best_single_fix(g, paths),
        "edge_count_cut_cost": analyze.node_count_cut_cost(g, paths),
        "applied": sorted(snap["fixed"]),
    }
