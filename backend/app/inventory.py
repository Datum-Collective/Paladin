"""Load data/inventory.yaml: the possible attack steps (nodes, edges with prior p, cost, match specs)."""
import os
from functools import lru_cache
from pathlib import Path

import yaml

from .models import Edge, Node


def seed_dir() -> Path:
    return Path(os.environ.get("SEED_DIR", Path(__file__).resolve().parents[2] / "data"))


@lru_cache(maxsize=1)
def load() -> dict:
    raw = yaml.safe_load((seed_dir() / "inventory.yaml").read_text())
    nodes = [Node(**n) for n in raw["nodes"]]
    edges = [Edge(**e) for e in raw["edges"]]
    ids = {n.id for n in nodes}
    for e in edges:
        if e.src not in ids or e.dst not in ids:
            raise ValueError(f"edge {e.id} references unknown node")
    return {"nodes": nodes, "edges": edges, "ips": raw.get("ips", {}), "company": raw.get("company", "")}
