import math

from app.analyze import best_single_fix, build_graph, min_cut_fix, severity, top_paths, total_risk
from app.models import Edge, Node
from conftest import sign_in


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


def test_impact_can_outrank_likelihood_with_small_k():
    nodes = [N("net", "external"), N("a", "host"), N("b", "host"),
             N("jA", "data", 8), N("jB", "data", 10)]
    edges = [E("e1", "net", "a", 0.95, 1), E("e2", "a", "jA", 0.95, 1),   # likeliest, risk .72
             E("e3", "net", "b", 0.9, 1), E("e4", "b", "jB", 0.9, 1)]     # less likely, risk .81
    g = build_graph(nodes, edges)
    top = top_paths(g, 1)
    assert top[0]["nodes"][-1] == "jB"


def test_zero_time_budget_still_returns_a_path():
    g = build_graph(*toy())
    assert len(top_paths(g, 5, budget_s=0.0)) >= 1


def test_combined_risk_is_a_probability_not_a_sum():
    from app.analyze import total_risk
    ps = [{"risk": 0.3}, {"risk": 0.3}, {"risk": 0.3}]
    assert abs(total_risk(ps) - (1 - 0.7 ** 3)) < 1e-9          # noisy-or
    assert total_risk([{"risk": 0.0}]) == 0 and total_risk([{"risk": 1.0}, {"risk": 0.5}]) == 1.0
    many_small = [{"risk": 0.02}] * 40
    assert total_risk(many_small) < 0.6                           # a sum would have been 0.8


def test_headline_severity_is_the_worst_path_not_the_aggregate(client):
    sign_in(client)
    client.post("/api/ingest", json={"format": "web_access", "lines": [
        '185.199.110.42 - - [14/May/2024:13:00:01 +0000] "GET /.env HTTP/1.1" 404 153 "-" "Nikto/2.1.6"']})
    p = client.get("/api/paths").json()
    worst = max(x["risk"] for x in p["paths"])
    assert p["worst"] == worst and p["severity"] == p["paths"][0]["severity"]
    g = client.get("/api/graph").json()
    assert g["severity"] == p["severity"] and g["worst"] == worst and g["risk"] <= 1.0
