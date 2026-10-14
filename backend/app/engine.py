"""Glue: events + inventory + applied fixes -> graph, ranked paths, fixes (computed, never stored)."""
from . import analyze, codescan, inventory, store
from .models import Edge, Node
from .correlate import correlate
from .narrate import narrate


def snapshot(ws: int, k: int = 10) -> dict:
    inv = inventory.load()
    cm = codescan.load_model(ws)
    all_nodes = inv["nodes"] + [Node(**n) for n in cm["nodes"]]
    all_edges = inv["edges"] + [Edge(**e) for e in cm["edges"]]
    events = store.get_events(ws)
    fixed = store.applied_fixes(ws)
    edges = correlate(all_edges, events)
    g = analyze.build_graph(all_nodes, edges, removed=fixed)
    paths = analyze.top_paths(g, k)
    by_id = {e.id: e for e in edges}
    labels = {n.id: n.label for n in all_nodes}
    for p in paths:
        p["narrative"], p["tactics"], p["hops"] = narrate(p, by_id, labels)
    return {
        "nodes": all_nodes, "edges": edges, "fixed": fixed, "graph": g, "paths": paths,
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
