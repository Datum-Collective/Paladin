"""Glue: events + inventory + applied fixes -> graph, ranked paths, fixes (computed, never stored)."""
from . import analyze, inventory, store
from .correlate import correlate
from .narrate import narrate


def snapshot(ws: int, k: int = 10) -> dict:
    inv = inventory.load()
    events = store.get_events(ws)
    fixed = store.applied_fixes(ws)
    edges = correlate(inv["edges"], events)
    g = analyze.build_graph(inv["nodes"], edges, removed=fixed)
    paths = analyze.top_paths(g, k)
    by_id = {e.id: e for e in edges}
    labels = {n.id: n.label for n in inv["nodes"]}
    for p in paths:
        p["narrative"], p["tactics"], p["hops"] = narrate(p, by_id, labels)
    return {
        "nodes": inv["nodes"], "edges": edges, "fixed": fixed, "graph": g, "paths": paths,
        "risk": analyze.total_risk(paths), "events": len(events),
    }


def fixes(snap: dict) -> dict:
    g, paths = snap["graph"], snap["paths"]
    return {
        "cheapest_cut": analyze.min_cut_fix(g, paths),
        "best_single": analyze.best_single_fix(g, paths),
        "edge_count_cut_cost": analyze.node_count_cut_cost(g, paths),
        "applied": sorted(snap["fixed"]),
    }
