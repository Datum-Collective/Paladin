"""Attack-path analysis: top-k paths by risk, cost-weighted min cut, greedy best single fix."""
import math
import time

import networkx as nx

from .models import Edge, Node

SRC, SINK = "__SOURCE__", "__SINK__"
MAX_K = 50
MAX_NODES = 2000
BANDS = [(0.30, "CRITICAL"), (0.10, "HIGH"), (0.03, "MEDIUM")]
DANGEROUS = 0.03  # MEDIUM and above feed the fix computation
P_FLOOR = 1e-6
CROWN_MIN = 8  # data nodes at or above this criticality are crown jewels


def severity(risk: float) -> str:
    for t, name in BANDS:
        if risk >= t:
            return name
    return "LOW"


def build_graph(nodes: list[Node], edges: list[Edge], removed: set[str] = frozenset()) -> nx.DiGraph:
    if len(nodes) > MAX_NODES:
        raise ValueError("graph too large")
    g = nx.DiGraph()
    for n in nodes:
        g.add_node(n.id, kind=n.kind, label=n.label, crit=n.criticality)
    for e in edges:
        if e.id in removed or e.src not in g or e.dst not in g:
            continue
        p = max(e.p, P_FLOOR)
        g.add_edge(e.src, e.dst, id=e.id, p=p, w=-math.log(p), cost=e.cost,
                   technique=e.technique, mitigation=e.mitigation)
    return g


def _augment(g: nx.DiGraph) -> nx.DiGraph:
    a = g.copy()
    a.add_node(SRC)
    a.add_node(SINK)
    for n, d in g.nodes(data=True):
        if d.get("kind") == "external":
            a.add_edge(SRC, n, id=f"src:{n}", p=1.0, w=0.0, cost=None)
        if d.get("kind") == "data" and d.get("crit", 0) >= CROWN_MIN:
            a.add_edge(n, SINK, id=f"sink:{n}", p=1.0, w=0.0, cost=None)
    return a


CANDIDATE_FACTOR = 4   # examine k*4 likeliest paths, then rank by risk (impact can reorder them)
MAX_CANDIDATES = 200
TIME_BUDGET_S = 2.0


def top_paths(g: nx.DiGraph, k: int = 10, budget_s: float = TIME_BUDGET_S) -> list[dict]:
    """Top-k paths by risk. Candidates come lazily from k-shortest-simple-paths (most likely first) and are
    re-ranked by risk = prod(p) x impact/10; the search stops at the candidate cap or the time budget."""
    k = max(1, min(k, MAX_K))
    a = _augment(g)
    want = min(k * CANDIDATE_FACTOR, MAX_CANDIDATES)
    deadline = time.monotonic() + budget_s
    raw = []
    try:
        for pth in nx.shortest_simple_paths(a, SRC, SINK, weight="w"):
            raw.append(pth)
            if len(raw) >= want or time.monotonic() > deadline:
                break
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []
    out = []
    for pth in raw:
        nodes = pth[1:-1]
        if len(nodes) < 2:
            continue
        eids, p = [], 1.0
        for u, v in zip(nodes, nodes[1:]):
            d = g[u][v]
            eids.append(d["id"])
            p *= d["p"]
        impact = g.nodes[nodes[-1]]["crit"]
        risk = p * impact / 10.0
        out.append({"nodes": nodes, "edges": eids, "p": p, "impact": impact, "risk": risk,
                    "severity": severity(risk)})
    out.sort(key=lambda r: -r["risk"])
    out = out[:k]
    for i, r in enumerate(out):
        r["id"] = f"p{i + 1}"
    return out


def total_risk(paths: list[dict]) -> float:
    return min(1.0, sum(p["risk"] for p in paths))


def _dangerous_edges(paths: list[dict]) -> set[str]:
    return {e for p in paths if p["risk"] >= DANGEROUS for e in p["edges"]}


def _edge_index(g: nx.DiGraph) -> dict[str, tuple[str, str]]:
    return {d["id"]: (u, v) for u, v, d in g.edges(data=True)}


def min_cut_fix(g: nx.DiGraph, paths: list[dict]) -> dict | None:
    """Cheapest set of cuttable edges separating source from sink over dangerous paths only."""
    danger = [p for p in paths if p["risk"] >= DANGEROUS]
    if not danger:
        return None
    idx = _edge_index(g)
    h = nx.DiGraph()
    for p in danger:
        for u, v in zip(p["nodes"], p["nodes"][1:]):
            d = g[u][v]
            if d["cost"] is None:
                h.add_edge(u, v)  # no capacity attribute = uncuttable
            else:
                h.add_edge(u, v, capacity=d["cost"])
        h.add_edge(SRC, p["nodes"][0])
        h.add_edge(p["nodes"][-1], SINK)
    try:
        value, (s_side, t_side) = nx.minimum_cut(h, SRC, SINK)
    except nx.NetworkXUnbounded:
        return None  # every separating cut needs an uncuttable edge
    cut = [(u, v) for u in s_side for v in h[u] if v in t_side]
    cut_ids = [g[u][v]["id"] for u, v in cut]
    return _fix_dict(g, danger, paths, cut_ids, float(value), idx)


def best_single_fix(g: nx.DiGraph, paths: list[dict]) -> dict | None:
    danger = [p for p in paths if p["risk"] >= DANGEROUS]
    gain: dict[str, float] = {}
    for p in danger:
        for e in p["edges"]:
            gain[e] = gain.get(e, 0.0) + p["risk"]
    idx = _edge_index(g)
    best = None
    for eid, r in gain.items():
        u, v = idx[eid]
        c = g[u][v]["cost"]
        if c is None:
            continue
        key = (r, -c)
        if best is None or key > best[0]:
            best = (key, eid, c)
    if best is None:
        return None
    return _fix_dict(g, danger, paths, [best[1]], float(best[2]), idx)


def _fix_dict(g, danger, all_paths, cut_ids, cost, idx) -> dict:
    cs = set(cut_ids)
    broken = [p for p in danger if cs & set(p["edges"])]
    tot = sum(p["risk"] for p in all_paths) or 1.0
    removed = sum(p["risk"] for p in all_paths if cs & set(p["edges"]))
    return {
        "edges": sorted(cs),
        "total_cost": cost,
        "paths_broken": len(broken),
        "risk_removed_pct": round(100.0 * removed / tot, 1),
        "mitigations": [{"edge": e, "technique": g[idx[e][0]][idx[e][1]]["technique"],
                         "mitigation": g[idx[e][0]][idx[e][1]]["mitigation"]} for e in sorted(cs)],
    }


def node_count_cut_cost(g: nx.DiGraph, paths: list[dict]) -> float | None:
    """Baseline for the demo: cost of the cut that minimises edge COUNT, ignoring remediation cost."""
    danger = [p for p in paths if p["risk"] >= DANGEROUS]
    if not danger:
        return None
    h = nx.DiGraph()
    for p in danger:
        for u, v in zip(p["nodes"], p["nodes"][1:]):
            h.add_edge(u, v, capacity=1 if g[u][v]["cost"] is not None else math.inf)
        h.add_edge(SRC, p["nodes"][0], capacity=math.inf)
        h.add_edge(p["nodes"][-1], SINK, capacity=math.inf)
    try:
        _, (s, t) = nx.minimum_cut(h, SRC, SINK)
    except nx.NetworkXUnbounded:
        return None
    return sum(g[u][v]["cost"] or 0 for u in s for v in h[u] if v in t and u != SRC and v != SINK)
