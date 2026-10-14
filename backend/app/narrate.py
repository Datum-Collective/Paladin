"""Template narratives: one sentence per hop with technique id and evidence ids, kill-chain ordered."""
import json
from functools import lru_cache

from .inventory import seed_dir

TACTIC_ORDER = ["reconnaissance", "initial-access", "execution", "persistence", "privilege-escalation",
                "defense-evasion", "credential-access", "discovery", "lateral-movement", "collection",
                "command-and-control", "exfiltration", "impact"]


@lru_cache(maxsize=1)
def subset() -> dict:
    p = seed_dir() / "attack_subset.json"
    return json.loads(p.read_text()) if p.exists() else {}


def technique(tid: str) -> dict:
    return subset().get("techniques", {}).get(tid, {"name": tid, "tactics": [], "mitigations": []})


def mitigation_name(mid: str) -> str:
    return subset().get("mitigations", {}).get(mid, mid)


def narrate(path: dict, edges_by_id: dict, labels: dict) -> tuple[str, list[str], list[dict]]:
    """Return (narrative, tactics in kill-chain order, per-hop detail)."""
    hops, sentences, tactics = [], [], set()
    for i, eid in enumerate(path["edges"]):
        e = edges_by_id[eid]
        t = technique(e.technique)
        tactics.update(t["tactics"])
        src, dst = labels.get(e.src, e.src), labels.get(e.dst, e.dst)
        how = f"{t['name']} ({e.technique})"
        if e.observed:
            ev = ", ".join(e.evidence[:3]) + ("..." if len(e.evidence) > 3 else "")
            sentences.append(f"{src} reached {dst} via {how}, confirmed by events {ev}.")
        else:
            sentences.append(f"{src} could reach {dst} via {how} (no events yet, prior only).")
        hops.append({"edge": eid, "src": e.src, "dst": e.dst, "technique": e.technique,
                     "technique_name": t["name"], "observed": e.observed, "p": round(e.p, 3),
                     "evidence": e.evidence, "mitigation": e.mitigation,
                     "mitigation_name": mitigation_name(e.mitigation)})
    order = sorted(tactics, key=lambda x: TACTIC_ORDER.index(x) if x in TACTIC_ORDER else 99)
    return " ".join(sentences), order, hops
