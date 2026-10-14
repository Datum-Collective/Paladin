"""Measure the real pipeline on a synthetic load. Nothing is hardcoded: every number is timed here.

Usage: python scripts/benchmark.py [sizes...]   (default 1000 10000 50000)
Writes data/benchmarks.json and docs/BENCHMARKS.md. Load is synthetic and generated from a fixed seed.
"""
import json
import os
import platform
import random
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("SEED_DIR", str(ROOT / "data"))
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apc-bench-")

from app import analyze, engine, store  # noqa: E402
from app.models import Edge, Node  # noqa: E402
from app.parsers.registry import parse_lines  # noqa: E402

USERS = ["www-data", "maya.patel", "nina.kapoor", "svc-backup", "carla.nunez"]
HOSTS = ["WEB-BO-01", "FILE-BO-01", "DC-BO-01"]
IPS = ["185.199.110.42", "203.0.113.9", "198.51.100.77", "10.44.30.10", "45.83.220.5"]


def gen(n: int, seed: int = 7) -> dict[str, list[str]]:
    rnd = random.Random(seed)
    out = {"linux_auth": [], "web_access": [], "snort_alert": []}
    for i in range(n):
        sec = i % 3600
        kind = i % 3
        if kind == 0:
            u, h, ip = rnd.choice(USERS), rnd.choice(HOSTS), rnd.choice(IPS)
            verb = "Accepted password" if rnd.random() < 0.3 else "Failed password"
            out["linux_auth"].append(
                f"May 14 {13 + sec // 3600:02d}:{(sec // 60) % 60:02d}:{sec % 60:02d} {h} sshd[{rnd.randint(100, 9999)}]: "
                f"{verb} for {u} from {rnd.choice(IPS)} port {rnd.randint(1024, 65000)} ssh2")
        elif kind == 1:
            path = rnd.choice(["/", "/claims", "/.env", "/wp-login.php", "/api/v1/status"])
            ua = rnd.choice(["Mozilla/5.0", "Nikto/2.1.6", "curl/8.1"])
            out["web_access"].append(
                f'{rnd.choice(IPS)} - - [14/May/2024:{13 + sec // 3600:02d}:{(sec // 60) % 60:02d}:{sec % 60:02d} +0000] '
                f'"GET {path} HTTP/1.1" {rnd.choice([200, 200, 404])} 512 "-" "{ua}"')
        else:
            out["snort_alert"].append(
                f"05/14-{13 + sec // 3600:02d}:{(sec // 60) % 60:02d}:{sec % 60:02d}.000000 [**] [1:2013504:3] "
                f"ET SCAN probe {rnd.randint(1, 9)} [**] [Classification: Attempted Recon] [Priority: 2] "
                f"{{TCP}} {rnd.choice(IPS)}:{rnd.randint(1024, 65000)} -> {rnd.choice(IPS)}:{rnd.choice([22, 80, 3389])}")
    return out


def run(n: int) -> dict:
    store.reset_connection()
    store.conn()
    ws = n  # fresh workspace per size
    lines = gen(n)
    t0 = time.perf_counter()
    events, rejected = [], 0
    for fmt, ls in lines.items():
        ev, bad = parse_lines(fmt, ls)
        events.extend(ev)
        rejected += len(bad)
    t1 = time.perf_counter()
    stored = store.add_events(ws, events)
    t2 = time.perf_counter()
    snap = engine.snapshot(ws, 10)
    t3 = time.perf_counter()
    tm = snap["timings"]
    confirmed = sum(1 for e in snap["edges"] if e.observed)
    return {
        "events": stored, "rejected": rejected,
        "parse_ms": round((t1 - t0) * 1000, 1), "parse_eps": round(len(events) / (t1 - t0)),
        "ingest_ms": round((t2 - t1) * 1000, 1), "ingest_eps": round(stored / (t2 - t1)),
        "correlate_ms": tm["correlate_ms"], "graph_ms": tm["graph_ms"], "paths_ms": tm["paths_ms"],
        "narrate_ms": tm["narrate_ms"], "analysis_ms": round((t3 - t2) * 1000, 1),
        "end_to_end_ms": round((t3 - t0) * 1000, 1),
        "end_to_end_eps": round(stored / (t3 - t0)),
        "confirmed_steps": confirmed, "ranked_paths": len(snap["paths"]),
        "top_severity": snap["paths"][0]["severity"] if snap["paths"] else None,
    }


def graph_scale(n_nodes: int, seed: int = 11) -> dict:
    """Synthetic layered attack graph: entry points -> layers of hosts/identities -> crown jewels."""
    rnd = random.Random(seed)
    layers = max(4, int(n_nodes ** 0.5) // 2)
    width = max(2, n_nodes // layers)
    nodes, edges, prev = [], [], []
    for i in range(3):
        nodes.append(Node(id=f"x{i}", kind="external", label=f"entry{i}", criticality=1))
        prev.append(f"x{i}")
    for L in range(layers):
        cur = []
        for j in range(width):
            nid = f"n{L}_{j}"
            nodes.append(Node(id=nid, kind="host", label=nid, criticality=rnd.randint(1, 7)))
            cur.append(nid)
        for v in cur:
            for u in rnd.sample(prev, min(len(prev), 3)):
                edges.append(Edge(id=f"{u}>{v}", src=u, dst=v, technique="T1021", p=round(rnd.uniform(0.2, 0.9), 2),
                                  cost=rnd.randint(1, 9)))
        prev = cur
    for k in range(3):
        nid = f"jewel{k}"
        nodes.append(Node(id=nid, kind="data", label=nid, criticality=9))
        for u in rnd.sample(prev, min(len(prev), 3)):
            edges.append(Edge(id=f"{u}>{nid}", src=u, dst=nid, technique="T1005", p=0.7, cost=rnd.randint(1, 9)))
    t0 = time.perf_counter()
    g = analyze.build_graph(nodes, edges)
    t1 = time.perf_counter()
    paths = analyze.top_paths(g, 10)
    t2 = time.perf_counter()
    saved, analyze.DANGEROUS = analyze.DANGEROUS, 0.0  # long synthetic paths score low; cut them all
    try:
        t2 = time.perf_counter()
        fix = analyze.min_cut_fix(g, paths)
    finally:
        analyze.DANGEROUS = saved
    t3 = time.perf_counter()
    return {"nodes": len(nodes), "edges": len(edges), "build_ms": round((t1 - t0) * 1000, 1),
            "top10_paths_ms": round((t2 - t1) * 1000, 1), "min_cut_ms": round((t3 - t2) * 1000, 1),
            "paths_found": len(paths), "cut_cost": fix["total_cost"] if fix else None}


def main() -> None:
    sizes = [int(a) for a in sys.argv[1:]] or [1000, 10000, 50000]
    runs = [run(n) for n in sizes]
    scale = [graph_scale(n) for n in (100, 500, 2000)]
    meta = {"python": platform.python_version(), "machine": platform.machine(), "system": platform.system(),
            "cpus": os.cpu_count(), "synthetic_load": True, "seed": 7,
            "generated": time.strftime("%Y-%m-%d %H:%M:%S")}
    (ROOT / "data" / "benchmarks.json").write_text(json.dumps({"meta": meta, "runs": runs, "graph_scale": scale}, indent=1))
    hdr = ("| events | parse eps | ingest eps | correlate ms | graph ms | paths ms | analysis ms | "
           "end-to-end ms | confirmed steps | ranked paths |")
    rows = [f"| {r['events']} | {r['parse_eps']} | {r['ingest_eps']} | {r['correlate_ms']} | {r['graph_ms']} | "
            f"{r['paths_ms']} | {r['analysis_ms']} | {r['end_to_end_ms']} | {r['confirmed_steps']} | "
            f"{r['ranked_paths']} |" for r in runs]
    md = (f"# Benchmarks\n\nMeasured by `scripts/benchmark.py` on {meta['system']} {meta['machine']}, "
          f"{meta['cpus']} CPUs, Python {meta['python']}, {meta['generated']}. Load is synthetic "
          f"(seeded generator), mixed Linux auth / web access / IDS lines through the real parsers, SQLite "
          f"store, correlation and path engine. In-process: HTTP and network latency are not included.\n\n"
          f"{hdr}\n|{'---|' * 10}\n" + "\n".join(rows) + "\n")
    srows = [f"| {x['nodes']} | {x['edges']} | {x['build_ms']} | {x['top10_paths_ms']} | {x['min_cut_ms']} | "
             f"{x['paths_found']} | {x['cut_cost']} |" for x in scale]
    md += ("\n## Graph scale (synthetic layered graph, 3 entry points, 3 crown jewels)\n\n"
           "| nodes | edges | build ms | top-10 paths ms | min cut ms | paths found | cut cost |\n"
           "|---|---|---|---|---|---|---|\n" + "\n".join(srows) + "\n")
    (ROOT / "docs" / "BENCHMARKS.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
