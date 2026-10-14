import math

from app.analyze import best_single_fix, build_graph, min_cut_fix, severity, top_paths, total_risk
from app.models import Edge, Node


def N(i, kind, crit=1):
    return Node(id=i, kind=kind, label=i, criticality=crit)


def E(i, s, d, p, cost=None, t="T1078", m="M1032"):
    return Edge(id=i, src=s, dst=d, p=p, cost=cost, technique=t, mitigation=m)


def toy():
    nodes = [N("net", "external"), N("a", "host"), N("b", "host"), N("c", "host"), N("db", "data", 10)]
    edges = [E("e1", "net", "a", 0.8, 5), E("e2", "a", "b", 0.5, 2), E("e3", "b", "db", 0.9, 4),
             E("e4", "a", "c", 0.5, 1), E("e5", "c", "db", 0.5, 3)]
    return nodes, edges


def test_top_path_and_risk():
    g = build_graph(*toy())
    ps = top_paths(g, 5)
    assert ps[0]["nodes"] == ["net", "a", "b", "db"]
    assert math.isclose(ps[0]["risk"], 0.8 * 0.5 * 0.9 * 1.0)
    assert len(ps) == 2
    assert ps[0]["risk"] >= ps[1]["risk"]


def test_min_cut_is_cost_weighted():
    g = build_graph(*toy())
    fix = min_cut_fix(g, top_paths(g, 5))
    # e2+e4 (cost 3) beats the single entry edge e1 (cost 5): cost, not edge count, decides
    assert set(fix["edges"]) == {"e2", "e4"} and fix["total_cost"] == 3
    nodes, edges = toy()
    edges[1].cost = 10
    edges[2].cost = 6
    g = build_graph(nodes, edges)
    fix = min_cut_fix(g, top_paths(g, 5))
    assert fix["edges"] == ["e1"] and fix["total_cost"] == 5


def test_best_single_fix_picks_max_risk_removed():
    g = build_graph(*toy())
    fix = best_single_fix(g, top_paths(g, 5))
    assert fix["edges"] == ["e1"] and fix["risk_removed_pct"] == 100.0


def test_p_one_and_near_zero():
    nodes, edges = toy()
    edges[0].p = 1.0
    edges[2].p = 1e-12
    g = build_graph(nodes, edges)
    ps = top_paths(g, 5)
    assert all(0 <= p["risk"] <= 1 for p in ps)


def test_disconnected_and_no_path():
    nodes, edges = toy()
    g = build_graph(nodes, [])
    assert top_paths(g, 5) == []
    assert min_cut_fix(g, []) is None and best_single_fix(g, []) is None
    assert total_risk([]) == 0


def test_all_uncuttable_gives_no_fix():
    nodes, edges = toy()
    for e in edges:
        e.cost = None
    g = build_graph(nodes, edges)
    assert min_cut_fix(g, top_paths(g, 5)) is None


def test_removed_edges_drop_risk():
    nodes, edges = toy()
    g = build_graph(nodes, edges, removed={"e1"})
    assert top_paths(g) == []


def test_severity():
    assert severity(0.5) == "CRITICAL" and severity(0.1) == "HIGH" and severity(0.01) == "LOW"
