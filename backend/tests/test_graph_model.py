from conftest import sign_in
"""The graph must describe only what the workspace actually contains."""
LOG = "May 14 13:05:11 WEB-BO-01 sshd[912]: Accepted password for www-data from 185.199.110.42 port 51544 ssh2"
HTML = ('<div id=a></div>\n<script>\n'
        'a.innerHTML = location.hash;\n'
        'b.innerHTML = location.search;\n'
        '</script>\n')
PY = ('from flask import Flask, request\nimport hashlib\napp = Flask(__name__)\n'
      '@app.post("/x")\ndef x():\n    return hashlib.md5(b"a").hexdigest()\n'
      'CORS(app, origins=["*"])\n')
INVENTORY_IDS = {"internet", "WEB-BO-01", "nina.kapoor", "FILE-BO-01", "claims-data", "phish-mail"}


def scan(c, files):
    sign_in(c)
    return c.post("/api/codescan", json={"repo": "t", "files": files}).json()


def test_code_only_workspace_contains_no_demo_company(client):
    scan(client, [{"path": "web/index.html", "content": HTML}])
    g = client.get("/api/graph").json()
    ids = {n["id"] for n in g["nodes"]}
    assert ids and not (ids & INVENTORY_IDS), ids & INVENTORY_IDS
    assert all(i.startswith("code:") for i in ids)
    assert all(e["id"].startswith("code:") for e in g["edges"])
    assert not any(n["label"] in ("Claims portal web server", "Phishing email") for n in g["nodes"])


def test_events_only_workspace_contains_no_code_nodes(client):
    sign_in(client)
    client.post("/api/ingest", json={"format": "linux_auth", "lines": [LOG]})
    ids = {n["id"] for n in client.get("/api/graph").json()["nodes"]}
    assert INVENTORY_IDS & ids and not any(i.startswith("code:") for i in ids)


def test_both_sources_are_separate_components(client):
    scan(client, [{"path": "web/index.html", "content": HTML}])
    client.post("/api/ingest", json={"format": "linux_auth", "lines": [LOG]})
    g = client.get("/api/graph").json()
    ids = {n["id"] for n in g["nodes"]}
    assert "internet" in ids and "code:internet" in ids       # distinct entry points, not glued together
    for e in g["edges"]:
        assert e["src"].startswith("code:") == e["dst"].startswith("code:")   # no edge crosses the two


def test_each_finding_is_its_own_node_and_path(client):
    scan(client, [{"path": "web/index.html", "content": HTML}])
    g = client.get("/api/graph").json()
    finding_nodes = [n for n in g["nodes"] if n["id"].startswith("code:finding:")]
    assert len(finding_nodes) == 2                       # two innerHTML sinks, two distinct weaknesses
    assert {n["label"] for n in finding_nodes} == {"Unescaped HTML sink (line 3)", "Unescaped HTML sink (line 4)"}
    paths = client.get("/api/paths").json()["paths"]
    through = {n for p in paths for n in p["nodes"] if n.startswith("code:finding:")}
    assert len(through) == 2                             # neither finding is dropped from the analysis


def test_entry_exposure_is_not_a_fix_and_fixes_target_findings(client):
    scan(client, [{"path": "app.py", "content": PY}])
    fx = client.get("/api/fixes").json()
    edges = (fx["cheapest_cut"] or {}).get("edges", []) + (fx["best_single"] or {}).get("edges", [])
    assert edges and all(e.startswith("code:") and not e.startswith("code:in:") for e in edges)
    g = client.get("/api/graph").json()
    entry = [e for e in g["edges"] if e["id"].startswith("code:in:")]
    assert entry and all(e["cost"] is None for e in entry)


def test_demo_edges_are_not_valid_targets_in_a_code_only_workspace(client):
    scan(client, [{"path": "app.py", "content": PY}])
    assert client.post("/api/remediations", json={"edges": ["scan-web"]}).status_code == 422
    good = client.get("/api/fixes").json()["best_single"]["edges"]
    assert client.post("/api/remediations", json={"edges": good}).status_code == 200


def test_graph_never_contains_edges_to_missing_nodes(client, monkeypatch):
    """Regression: a stored model with a skipped (invalid) node left edges pointing at nothing, and the browser's
    graph library throws on such an edge, which blanked the whole app."""
    from app import codescan
    sign_in(client)
    model = {"nodes": [{"id": "a", "kind": "external", "label": "A", "criticality": 1},
                       {"id": "b", "kind": "data", "label": "B", "criticality": 9},
                       {"id": "bad", "kind": "data", "label": "X", "criticality": 99}],      # invalid: dropped
             "edges": [{"id": "e1", "src": "a", "dst": "b", "technique": "T1190", "p": 0.5},
                       {"id": "e2", "src": "a", "dst": "bad", "technique": "T1190", "p": 0.5},
                       {"id": "e1", "src": "a", "dst": "b", "technique": "T1190", "p": 0.5}]}   # duplicate id
    monkeypatch.setattr(codescan, "load_model", lambda ws: model)
    g = client.get("/api/graph").json()
    ids = {n["id"] for n in g["nodes"]}
    assert ids == {"a", "b"}
    assert [e["id"] for e in g["edges"]] == ["e1"]
    assert all(e["src"] in ids and e["dst"] in ids for e in g["edges"])
