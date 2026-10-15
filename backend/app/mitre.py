"""Offline MITRE knowledge pack (ATT&CK Enterprise, CWE, CAPEC) for grounding fixes. Built by
scripts/build_mitre_pack.py from MITRE's own downloads; nothing here is written by us or by a model.

What MITRE does and does not link: CWE -> CAPEC (Related_Attack_Patterns) is dense; CAPEC -> ATT&CK (Taxonomy_Mappings)
is sparse (MITRE maps 175 of 558 attack patterns, and none for SQL or OS command injection). When Paladin shows an
ATT&CK technique for a code finding that MITRE does not link, that link is Paladin's own mapping and is labelled so."""
import json
import re
from functools import lru_cache

from . import inventory

ID_RE = re.compile(r"^(CWE-\d{1,5}|CAPEC-\d{1,5}|T\d{4}(\.\d{3})?|M\d{4})$")


@lru_cache(maxsize=1)
def pack() -> dict:
    p = inventory.seed_dir() / "mitre.json"
    if not p.exists():
        return {"source": {}, "attack": {}, "mitigations": {}, "cwe": {}, "capec": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def _table(i: str) -> str | None:
    if i.startswith("CWE-"):
        return "cwe"
    if i.startswith("CAPEC-"):
        return "capec"
    if i.startswith("T"):
        return "attack"
    if i.startswith("M"):
        return "mitigations"
    return None


def normalize(i: str) -> str:
    i = str(i or "").strip().upper()
    if re.fullmatch(r"\d{1,5}", i):
        return f"CWE-{i}"
    return i.replace("CWE ", "CWE-").replace("CAPEC ", "CAPEC-")


def get(i: str) -> dict | None:
    i = normalize(i)
    t = _table(i)
    e = pack()[t].get(i) if t else None
    return {"id": i, "catalog": t, **e} if e else None


def exists(i: str) -> bool:
    return get(i) is not None


def related(cwe: str) -> set[str]:
    """Every id MITRE itself connects to this weakness: the CWE, its parents and children, their CAPEC attack
    patterns, the ATT&CK techniques those patterns map to, and those techniques' mitigations."""
    p = pack()
    c = normalize(cwe)
    if c not in p["cwe"]:
        return set()
    family = {c, *p["cwe"][c]["parents"], *(k for k, w in p["cwe"].items() if c in w["parents"])}
    out = set(family)
    for w in family:
        for cap in p["cwe"].get(w, {}).get("capec", []):
            out.add(cap)
            for t in p["capec"].get(cap, {}).get("attack", []):
                out.add(t)
                out.update(p["attack"].get(t, {}).get("mitigations", []))
    return out


def brief(cwe: str, technique: str | None = None) -> dict:
    """What the agent is handed about a finding: MITRE's own words, with every link's provenance."""
    p = pack()
    c = normalize(cwe)
    w = p["cwe"].get(c)
    out: dict = {"cwe": None, "capec": [], "attack_from_mitre": [], "paladin_technique": None}
    if w:
        out["cwe"] = {"id": c, "name": w["name"], "description": w["description"], "mitigations": w["mitigations"],
                      "url": w["url"]}
        for cap in w["capec"][:4]:
            a = p["capec"][cap]
            out["capec"].append({"id": cap, "name": a["name"], "severity": a["severity"], "attack": a["attack"]})
        out["attack_from_mitre"] = sorted({t for cap in w["capec"] for t in p["capec"][cap]["attack"]})
    if technique and technique in p["attack"] and technique not in out["attack_from_mitre"]:
        t = p["attack"][technique]
        out["paladin_technique"] = {"id": technique, "name": t["name"],
                                    "note": "Paladin's mapping for this finding; MITRE does not link it to the CWE"}
    return out


def search(query: str, limit: int = 8) -> list[dict]:
    q = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2]
    if not q:
        return []
    hits = []
    for table in ("cwe", "capec", "attack", "mitigations"):
        for i, e in pack()[table].items():
            hay = (e.get("name", "") + " " + e.get("description", "")).lower()
            score = sum(hay.count(w) for w in q) + 3 * sum(w in e.get("name", "").lower() for w in q)
            if score:
                hits.append((score, i, e.get("name", "")))
    hits.sort(key=lambda h: (-h[0], h[1]))
    return [{"id": i, "name": n} for _, i, n in hits[:limit]]


def source() -> dict:
    return pack().get("source", {})
