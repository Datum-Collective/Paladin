"""Workspace-grounded assistant: builds the system prompt from facts the engine already computed.

The model never decides risk or fixes (that stays in analyze.py); it explains and answers questions about the
computed paths. Anything that looks like a credential is masked before text leaves the process."""
import json
import re

from . import analyze, engine

MAX_MESSAGES = 40
MAX_CONTENT = 8000
MAX_TOTAL = 60000
_SECRET = re.compile(
    r"(sk-ant-[A-Za-z0-9_\-]{10,}|sk-[A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9\-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)")

SYSTEM = (
    "You are the analysis assistant inside Paladin, a security tool that turns logs and code scans into ranked "
    "attack paths. Answer using ONLY the JSON workspace facts below. If the facts do not contain the answer, say "
    "what is missing instead of guessing. Never invent hosts, accounts, commands or findings. Risk scores and fix "
    "rankings were computed by Paladin and are not yours to change; explain them. Any step that changes a system "
    "needs a human's approval: say so. Be concise and use plain text.\n\nWORKSPACE FACTS (JSON):\n")


def redact(text: str) -> str:
    return _SECRET.sub("[redacted]", text)


def context(ws: int, limit: int = 7000) -> str:
    """Compact JSON of the computed facts. Always valid JSON and always keeps the fixes: when over budget the
    lowest-ranked paths are dropped first, then hop detail, rather than cutting the string."""
    s = engine.snapshot(ws, 8)
    fx = engine.fixes(s)
    worst = analyze.worst_risk(s["paths"])
    fixes = {k: ({"cost": v["total_cost"], "paths_broken": v["paths_broken"], "risk_removed_pct": v["risk_removed_pct"],
                  "edges": v["edges"]} if v else None)
             for k, v in (("cheapest_cut", fx.get("cheapest_cut")), ("best_single", fx.get("best_single")))}

    def paths(n: int, hops: bool) -> list[dict]:
        out = []
        for p in s["paths"][:n]:
            d = {"id": p["id"], "severity": p["severity"], "risk": round(p["risk"], 3), "nodes": p["nodes"],
                 "tactics": p["tactics"], "narrative": p["narrative"][:400]}
            if hops:
                d["hops"] = [{"from": h["src"], "to": h["dst"], "technique": h["technique"],
                              "confirmed_by_events": h["observed"], "mitigation": h.get("mitigation")} for h in p["hops"]]
            out.append(d)
        return out

    def build(n: int, hops: bool) -> str:
        facts = {"events": s["events"], "combined_risk": s["risk"], "worst_risk": worst,
                 "severity": analyze.severity(worst), "fixes": fixes, "paths": paths(n, hops)}
        return redact(json.dumps(facts, separators=(",", ":")))

    for hops in (True, False):
        for n in range(len(s["paths"][:8]), -1, -1):
            text = build(n, hops)
            if len(text) <= limit:
                return text
    return build(0, False)


def system_prompt(ws: int, include_context: bool) -> str:
    if not include_context:
        return "You are a concise, accurate assistant for a security analyst. Plain text."
    return SYSTEM + context(ws)


def clean_messages(messages: list[dict]) -> list[dict]:
    return [{"role": m["role"], "content": redact(m["content"])} for m in messages]
