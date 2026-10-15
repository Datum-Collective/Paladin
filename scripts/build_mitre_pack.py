"""Build data/mitre.json: an offline MITRE knowledge pack (ATT&CK Enterprise, CWE, CAPEC) for the fixing agent.

Usage (inputs are MITRE's official downloads; nothing else is read):
    python -I scripts/build_mitre_pack.py <enterprise-attack.json> <cwec_vX.xml> <capec_latest.xml> data/mitre.json

Sources:
    ATT&CK  https://github.com/mitre-attack/attack-stix-data  (enterprise-attack/enterprise-attack.json)
    CWE     https://cwe.mitre.org/data/xml/cwec_latest.xml.zip
    CAPEC   https://capec.mitre.org/data/xml/capec_latest.xml
Deprecated, revoked and obsolete entries are dropped. Text is shortened, never rewritten: what the agent quotes is
MITRE's own wording. Links between the three catalogues come from MITRE too (CWE Related_Attack_Patterns, CAPEC
Related_Weaknesses and Taxonomy_Mappings to ATT&CK)."""
import json
import re
import sys
import xml.etree.ElementTree as ET

DESC, MIT = 500, 320


def short(text: str, n: int) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    t = re.sub(r"\(Citation: [^)]*\)", "", t).strip()
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"


def text_of(el) -> str:
    return "" if el is None else " ".join(el.itertext())


def attack(path: str) -> tuple[dict, dict, str]:
    data = json.load(open(path, encoding="utf-8"))
    objs = data["objects"]
    version = next((o.get("x_mitre_version") for o in objs if o.get("type") == "x-mitre-collection"), "")
    live = [o for o in objs if not o.get("revoked") and not o.get("x_mitre_deprecated")]
    by_ref = {o["id"]: o for o in live}
    ext = lambda o: next((r["external_id"] for r in o.get("external_references", [])  # noqa: E731
                          if r.get("source_name") == "mitre-attack"), None)
    techniques, mitigations = {}, {}
    for o in live:
        if o["type"] == "attack-pattern" and ext(o):
            techniques[ext(o)] = {"name": o["name"], "tactics": [p["phase_name"] for p in o.get("kill_chain_phases", [])],
                                  "description": short(o.get("description", ""), DESC), "mitigations": [],
                                  "url": f"https://attack.mitre.org/techniques/{ext(o).replace('.', '/')}/"}
        elif o["type"] == "course-of-action" and ext(o) and ext(o).startswith("M"):
            mitigations[ext(o)] = {"name": o["name"], "description": short(o.get("description", ""), MIT)}
    for o in live:
        if o["type"] == "relationship" and o.get("relationship_type") == "mitigates":
            m, t = by_ref.get(o["source_ref"]), by_ref.get(o["target_ref"])
            if m and t and ext(m) in mitigations and ext(t) in techniques:
                techniques[ext(t)]["mitigations"].append(ext(m))
    for t in techniques.values():
        t["mitigations"] = sorted(set(t["mitigations"]))
    return techniques, mitigations, version


def cwe(path: str) -> tuple[dict, str]:
    root = ET.parse(path).getroot()
    ns = {"c": root.tag[1:root.tag.index("}")]}
    out = {}
    for w in root.iterfind("c:Weaknesses/c:Weakness", ns):
        if w.get("Status") in ("Deprecated", "Obsolete"):
            continue
        cid = f"CWE-{w.get('ID')}"
        mits = []
        for m in w.iterfind("c:Potential_Mitigations/c:Mitigation", ns):
            d = short(text_of(m.find("c:Description", ns)), MIT)
            if d:
                mits.append({"phase": text_of(m.find("c:Phase", ns)).strip(), "text": d})
        out[cid] = {
            "name": w.get("Name"), "abstraction": w.get("Abstraction"),
            "description": short(text_of(w.find("c:Description", ns)), DESC),
            "consequences": sorted({text_of(i).strip() for i in w.iterfind("c:Common_Consequences/c:Consequence/c:Impact", ns)}),
            "mitigations": mits[:4],
            "capec": sorted({f"CAPEC-{r.get('CAPEC_ID')}" for r in w.iterfind("c:Related_Attack_Patterns/c:Related_Attack_Pattern", ns)}),
            "parents": sorted({f"CWE-{r.get('CWE_ID')}" for r in w.iterfind("c:Related_Weaknesses/c:Related_Weakness", ns)
                               if r.get("Nature") == "ChildOf"}),
            "url": f"https://cwe.mitre.org/data/definitions/{w.get('ID')}.html",
        }
    return out, root.get("Version", "")


def capec(path: str) -> tuple[dict, str]:
    root = ET.parse(path).getroot()
    ns = {"c": root.tag[1:root.tag.index("}")]}
    out = {}
    for a in root.iterfind("c:Attack_Patterns/c:Attack_Pattern", ns):
        if a.get("Status") in ("Deprecated", "Obsolete"):
            continue
        aid = f"CAPEC-{a.get('ID')}"
        tech = []
        for m in a.iterfind("c:Taxonomy_Mappings/c:Taxonomy_Mapping", ns):
            if m.get("Taxonomy_Name") == "ATTACK":
                e = text_of(m.find("c:Entry_ID", ns)).strip()
                if e:
                    tech.append("T" + e.lstrip("T"))
        out[aid] = {
            "name": a.get("Name"),
            "description": short(text_of(a.find("c:Description", ns)), DESC),
            "severity": text_of(a.find("c:Typical_Severity", ns)).strip(),
            "likelihood": text_of(a.find("c:Likelihood_Of_Attack", ns)).strip(),
            "cwe": sorted({f"CWE-{r.get('CWE_ID')}" for r in a.iterfind("c:Related_Weaknesses/c:Related_Weakness", ns)}),
            "attack": sorted(set(tech)),
            "mitigations": [short(text_of(m), MIT) for m in a.iterfind("c:Mitigations/c:Mitigation", ns)][:4],
            "url": f"https://capec.mitre.org/data/definitions/{a.get('ID')}.html",
        }
    return out, root.get("Version", "")


def main(attack_path, cwe_path, capec_path, out_path):
    techniques, mitigations, av = attack(attack_path)
    weaknesses, cv = cwe(cwe_path)
    patterns, pv = capec(capec_path)
    # keep only links that resolve inside the pack, so every id the agent is shown can be looked up
    for w in weaknesses.values():
        w["capec"] = [c for c in w["capec"] if c in patterns]
        w["parents"] = [p for p in w["parents"] if p in weaknesses]
    for p in patterns.values():
        p["cwe"] = [c for c in p["cwe"] if c in weaknesses]
        p["attack"] = [t for t in p["attack"] if t in techniques]
    pack = {"source": {"attack": {"name": "MITRE ATT&CK Enterprise", "version": av,
                                  "url": "https://github.com/mitre-attack/attack-stix-data"},
                       "cwe": {"name": "MITRE CWE", "version": cv, "url": "https://cwe.mitre.org/data/downloads.html"},
                       "capec": {"name": "MITRE CAPEC", "version": pv, "url": "https://capec.mitre.org/data/downloads.html"},
                       "terms": "ATT&CK, CWE and CAPEC are MITRE works used under their terms of use"},
            "attack": techniques, "mitigations": mitigations, "cwe": weaknesses, "capec": patterns}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(pack, f, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    print(f"ATT&CK {av}: {len(techniques)} techniques, {len(mitigations)} mitigations; CWE {cv}: {len(weaknesses)}; "
          f"CAPEC {pv}: {len(patterns)} -> {out_path}")


if __name__ == "__main__":
    main(*sys.argv[1:5])
