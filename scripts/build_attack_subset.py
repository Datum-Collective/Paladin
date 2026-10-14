"""Trim the full MITRE ATT&CK STIX bundle to the techniques used in inventory.yaml (<1 MB).

Usage: python -I scripts/build_attack_subset.py data/attack/enterprise-attack.json data/inventory.yaml data/attack_subset.json
Source: https://github.com/mitre-attack/attack-stix-data (enterprise-attack.json).
"""
import json
import sys

import yaml


def ext_id(o):
    for r in o.get("external_references", []):
        if r.get("source_name") == "mitre-attack":
            return r.get("external_id")


# techniques referenced by backend/app/codescan.py rules (a test keeps these in sync)
CODESCAN = {"T1552.001", "T1059", "T1190", "T1557", "T1110", "T1189", "T1005"}


def main(stix_path, inv_path, out_path):
    wanted = {e["technique"] for e in yaml.safe_load(open(inv_path))["edges"]} | CODESCAN
    objs = json.load(open(stix_path))["objects"]
    live = [o for o in objs if not o.get("revoked") and not o.get("x_mitre_deprecated")]
    tech = {o["id"]: o for o in live if o["type"] == "attack-pattern" and ext_id(o) in wanted}
    mits = {o["id"]: o for o in live if o["type"] == "course-of-action"}
    out_t = {}
    for sid, o in tech.items():
        out_t[ext_id(o)] = {"name": o["name"], "tactics": [p["phase_name"] for p in o.get("kill_chain_phases", [])],
                            "mitigations": []}
    out_m = {}
    for r in live:
        if r["type"] == "relationship" and r["relationship_type"] == "mitigates" and r["target_ref"] in tech \
                and r["source_ref"] in mits:
            m = mits[r["source_ref"]]
            out_t[ext_id(tech[r["target_ref"]])]["mitigations"].append(ext_id(m))
            out_m[ext_id(m)] = m["name"]
    missing = wanted - set(out_t)
    if missing:
        print("WARNING: techniques not found:", sorted(missing), file=sys.stderr)
    json.dump({"source": "MITRE ATT&CK Enterprise (Apache-2.0 / ATT&CK terms of use)", "techniques": out_t,
               "mitigations": out_m}, open(out_path, "w"), indent=1, sort_keys=True)


if __name__ == "__main__":
    main(*sys.argv[1:4])
