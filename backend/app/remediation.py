"""Remediation lifecycle: proposed -> approved -> executed -> verified (or failed / rolled_back).

Deciding WHAT to cut is analyze.py (deterministic). This module records, approves, executes through a
connector, and verifies against later events. Every transition is audited.
"""
import time

import json

from . import ai, codefix, codescan, engine, inventory, store, supa
from .correlate import matches
from .narrate import mitigation_name, technique

STATES = ("proposed", "approved", "executed", "verified", "failed", "rolled_back")
NEXT = {"proposed": {"approved", "rolled_back"}, "approved": {"executed", "rolled_back"}, "executed": {"verified", "failed", "rolled_back"},
        "verified": {"rolled_back"}, "failed": {"rolled_back"}, "rolled_back": set()}

STEPS = {
    "M1032": ["Enforce multi-factor authentication for the affected account(s) and remote access paths.",
              "Revoke active sessions and re-enrol the second factor."],
    "M1027": ["Rotate the exposed credential and enforce the password policy (length, uniqueness).",
              "Remove credentials from files, scripts and shell history on the source host."],
    "M1026": ["Remove standing admin rights; use just-in-time privileged access.",
              "Audit members of privileged groups and remove unused ones."],
    "M1050": ["Place the exposed application behind exploit protection (WAF / patched build).",
              "Block the scanner source at the edge."],
    "M1038": ["Block interactive shells for the service account (nologin, restricted sudoers).",
              "Apply execution allow-listing on the host."],
    "M1030": ["Restrict RDP/SMB between the DMZ and server VLANs to jump hosts only."],
    "M1022": ["Tighten ACLs on the data share to named groups; remove inherited broad access."],
    "M1017": ["Run targeted phishing awareness training; add mail filtering rules for the lure."],
}


def _audit(ws: int, rem: int, actor: str, action: str, detail: str = "") -> None:
    supa.insert("audit", {"ws": ws, "user_id": supa.user_id(), "rem": rem, "actor": actor[:320], "action": action,
                          "detail": detail[:500], "ts": time.time()}, returning=None)


def _row(r) -> dict:
    d = dict(r)
    d.pop("user_id", None)
    d["edges"] = [e for e in d["edges"] if isinstance(e, str)] if isinstance(d.get("edges"), list) else []
    d["ai_drafted"] = bool(d["ai_drafted"])
    for k, want in (("files", list), ("finding_ids", list)):
        if not isinstance(d.get(k), want):
            d[k] = []
    d.setdefault("kind", "model")
    return d


def _facts(ws: int, edge_ids: list[str]) -> dict:
    snap = engine.snapshot(ws)
    by_id = {e.id: e for e in snap["edges"]}
    out = []
    for eid in edge_ids:
        e = by_id[eid]
        t = technique(e.technique)
        out.append({"edge": eid, "from": e.src, "to": e.dst, "technique": e.technique, "technique_name": t["name"],
                    "mitigation": e.mitigation, "mitigation_name": mitigation_name(e.mitigation),
                    "observed": e.observed, "evidence_event_ids": e.evidence[:5], "cost": e.cost})
    return {"steps_to_close": out, "risk_now": round(snap["risk"], 3)}


def template_runbook(facts: dict) -> str:
    lines = []
    for i, s in enumerate(facts["steps_to_close"], 1):
        lines.append(f"{i}. Close {s['from']} -> {s['to']} ({s['technique']} {s['technique_name']})"
                     f"{' [observed: ' + ', '.join(s['evidence_event_ids']) + ']' if s['observed'] else ''}")
        for st in STEPS.get(s["mitigation"], [f"Apply mitigation {s['mitigation']} {s['mitigation_name']}."]):
            lines.append(f"   - {st}")
    lines.append("Verify: new events must stop matching these steps; risk should fall after re-analysis.")
    return "\n".join(lines)


def propose(ws: int, actor: str, edge_ids: list[str], title: str) -> dict:
    valid = {e.id for e in engine.workspace_model(ws)[1]}
    if not edge_ids or any(e not in valid for e in edge_ids):
        raise ValueError("unknown edge id")
    code = [e for e in edge_ids if codefix.is_code_edge(e)]
    if code and len(code) != len(edge_ids):
        raise ValueError("Code fixes and log-environment fixes are separate remediations. Propose them one at a time.")
    if code and codefix.scan_running(ws):
        raise ValueError(codefix.STILL_RUNNING)
    if code and codefix.latest_job(ws) is not None:
        return _propose_code(ws, actor, edge_ids, title)
    # a code model with no repository scan behind it (findings uploaded through the API): there is no source copy to
    # patch, so this stays a planning record and says so
    no_source = bool(code)
    facts = _facts(ws, edge_ids)
    text = ai.draft(facts)
    runbook, used_ai = (text, True) if text else (template_runbook(facts), False)
    if no_source:
        runbook = ("No source copy is available for these findings (they were uploaded, not scanned from a "
                   "repository), so this is a plan only: no files are changed.\n" + runbook)
    now = time.time()
    rid = supa.insert("remediations", {
        "ws": ws, "user_id": supa.user_id(), "edges": sorted(set(edge_ids)), "state": "proposed", "title": title[:120],
        "runbook": runbook[:20000], "ai_drafted": bool(used_ai), "connector": "model", "created": now, "updated": now,
    }, returning="id")[0]["id"]
    _audit(ws, rid, actor, "proposed", ",".join(edge_ids))
    return get(ws, rid)


def _propose_code(ws: int, actor: str, edge_ids: list[str], title: str) -> dict:
    try:
        p = codefix.plan(ws, edge_ids)
    except codefix.FixError as e:
        raise ValueError(str(e)) from None
    now = time.time()
    rid = supa.insert("remediations", {
        "ws": ws, "user_id": supa.user_id(), "edges": sorted(set(edge_ids)), "state": "proposed", "title": title[:120],
        "runbook": codefix.summary_runbook(p)[:20000], "ai_drafted": any(f["method"] == "haiku" for f in p["fixed"]),
        "connector": "git", "created": now, "updated": now, "kind": "code", "job": p["job"], "patch": p["patch"],
        "files": p["files"], "finding_ids": p["finding_ids"], "applied": "",
    }, returning="id")[0]["id"]
    _audit(ws, rid, actor, "proposed", f"{len(p['fixed'])} fix(es) in {len(p['files'])} file(s)")
    out = get(ws, rid)
    out["plan"] = {"fixed": p["fixed"], "manual": p["manual"]}
    return out


def get(ws: int, rid: int) -> dict:
    r = supa.first("remediations", {"id": supa.eq(rid), "ws": supa.eq(ws)})
    if not r:
        raise KeyError(rid)
    return _row(r)


def list_(ws: int) -> list[dict]:
    return [_row(r) for r in supa.select("remediations", {"ws": supa.eq(ws)}, order="id.desc")]


def history(ws: int, limit: int = 100) -> list[dict]:
    """Every remediation step for a workspace, newest first, with the remediation's title and current state."""
    steps = supa.select("audit", {"ws": supa.eq(ws)}, columns="id,rem,actor,action,detail,ts", order="id.desc",
                        limit=limit)
    rems = {r["id"]: r for r in supa.select("remediations", {"ws": supa.eq(ws), "id": supa.in_({a["rem"] for a in steps})},
                                            columns="id,title,state")} if steps else {}
    return [{"id": a["id"], "actor": a["actor"], "action": a["action"], "detail": a["detail"], "ts": a["ts"],
             "title": (rems.get(a["rem"]) or {}).get("title"), "state": (rems.get(a["rem"]) or {}).get("state")}
            for a in steps]


def audit_log(ws: int, rid: int) -> list[dict]:
    return supa.select("audit", {"ws": supa.eq(ws), "rem": supa.eq(rid)}, columns="actor,action,detail,ts",
                       order="id.asc")


def _set(ws: int, rid: int, state: str, actor: str, detail: str = "", **cols) -> dict:
    cur = get(ws, rid)
    if state not in NEXT[cur["state"]]:
        raise ValueError(f"cannot go from {cur['state']} to {state}")
    # conditional on the state we checked, so two concurrent clicks cannot both make the same transition
    done = supa.update("remediations", {"id": supa.eq(rid), "ws": supa.eq(ws), "state": supa.eq(cur["state"])},
                       {"state": state, "updated": time.time(), **cols}, returning="id")
    if not done:
        raise ValueError(f"cannot go from {cur['state']} to {state}: it changed meanwhile")
    _audit(ws, rid, actor, state, detail)
    return get(ws, rid)


def approve(ws: int, rid: int, actor: str) -> dict:
    return _set(ws, rid, "approved", actor)


def execute(ws: int, rid: int, actor: str, applied_to: str = "") -> dict:
    """Model connector: closes the edges in the analysed environment. This is NOT a change to real hosts;
    a real connector would replace this call and the state machine stays the same. Code remediations are
    applied by execute_code() instead, which changes files (or opens a pull request) before recording this."""
    cur = get(ws, rid)
    if cur["state"] != "approved":
        raise ValueError(f"cannot go from {cur['state']} to executed")
    if cur["kind"] == "code":
        return _set(ws, rid, "executed", actor, f"applied to {applied_to}"[:480], applied=applied_to[:480],
                    mark=store.event_count(ws))
    def live(snap):  # paths an analyst would act on
        return sum(1 for p in snap["paths"] if p["severity"] in ("CRITICAL", "HIGH", "MEDIUM"))

    b = engine.snapshot(ws)
    store.apply_fix(ws, cur["edges"])
    a = engine.snapshot(ws)
    return _set(ws, rid, "executed", actor,
                f"connector={cur['connector']} risk {b['risk']:.3f}->{a['risk']:.3f} paths {live(b)}->{live(a)}",
                mark=store.event_count(ws), risk_before=round(b["risk"], 4), risk_after=round(a["risk"], 4),
                paths_before=live(b), paths_after=live(a))


def verify(ws: int, rid: int, actor: str) -> dict:
    """Verified only if (a) the edges are closed in the graph and (b) no event ingested AFTER execution still
    matches any of them. Otherwise failed, with the offending event ids as the note."""
    cur = get(ws, rid)
    if cur["state"] != "executed":
        raise ValueError(f"cannot go from {cur['state']} to verified")
    if cur["kind"] == "code":
        return _verify_code(ws, rid, actor, cur)
    from .models import Edge
    inv = {e.id: e for e in engine.workspace_model(ws)[1]}
    later = store.get_events(ws)[cur["mark"]:]
    still = [ev.id for ev in later for eid in cur["edges"] if matches(inv[eid], ev)]
    closed = set(cur["edges"]) <= store.applied_fixes(ws)
    if closed and not still:
        return _set(ws, rid, "verified", actor, "no matching events since execution")
    why = f"still observed after fix: {','.join(sorted(set(still))[:10])}" if still else "edges not closed"
    return _set(ws, rid, "failed", actor, why, note=why)


def verify_remote(ws: int, rid: int, actor: str, contents: dict) -> dict:
    """GitHub repositories: `contents` is what the default branch holds NOW, fetched by the caller after it saw the
    pull request merged. Verification never passes on anything but the real repository."""
    cur = get(ws, rid)
    if cur["state"] != "executed":
        raise ValueError(f"cannot go from {cur['state']} to verified")
    return _verify_code(ws, rid, actor, cur, contents)


def _verify_code(ws: int, rid: int, actor: str, cur: dict, remote_contents: dict | None = None) -> dict:
    """Read the files as they are now: from the folder, or from the default branch once the pull request is merged.
    Findings and the graph change only when the check passed."""
    try:
        kind, where = codefix.target(_job_repo(ws, cur))
        if kind == "local":
            def read(path):
                try:
                    p = codefix.safe_join(where, path)
                except codefix.FixError:
                    return None
                try:
                    return p.read_text(encoding="utf-8") if p.is_file() and not p.is_symlink() else None
                except (OSError, UnicodeDecodeError):
                    return None
            res = codefix.verify_files(read, cur["files"])
            scope = "the files on disk"
        else:
            if remote_contents is None:
                raise ValueError("The pull request has to be merged before this can be verified. Merge it on GitHub, "
                                 "then verify again.")
            res = codefix.verify_files(remote_contents.get, cur["files"])
            scope = "the merged files on the default branch"
    except codefix.FixError as e:
        raise ValueError(str(e)) from None
    if res["ok"]:
        def live(snap):
            return sum(1 for p in snap["paths"] if p["severity"] in ("CRITICAL", "HIGH", "MEDIUM"))
        b = engine.snapshot(ws)
        codescan.set_applied(ws, cur["finding_ids"], True, cur.get("job"))
        a = engine.snapshot(ws)
        detail = f"checked {scope}: parses, targeted rules no longer match. Tests were not run."
        if res["notes"]:
            detail += " " + "; ".join(res["notes"])
        return _set(ws, rid, "verified", actor, detail[:480], risk_before=round(b["risk"], 4),
                    risk_after=round(a["risk"], 4), paths_before=live(b), paths_after=live(a))
    why = "; ".join(res["problems"])[:480]
    return _set(ws, rid, "failed", actor, why, note=why)


def _job_repo(ws: int, cur: dict) -> str:
    r = supa.first("jobs", {"id": supa.eq(cur["job"]), "ws": supa.eq(ws)}, columns="repo_url") if cur.get("job") else None
    if not r:
        raise ValueError("The scan this fix came from no longer exists.")
    return r["repo_url"]


def rollback(ws: int, rid: int, actor: str) -> dict:
    cur = get(ws, rid)
    if cur["kind"] == "code":
        return _rollback_code(ws, rid, actor, cur)
    out = _set(ws, rid, "rolled_back", actor)
    keep = set()
    for other in list_(ws):
        if other["id"] != rid and other["state"] in ("executed", "verified"):
            keep |= set(other["edges"])
    store.remove_fixes(ws, sorted(set(cur["edges"]) - keep))
    return out


def _rollback_code(ws: int, rid: int, actor: str, cur: dict) -> dict:
    if "rolled_back" not in NEXT[cur["state"]]:
        raise ValueError(f"cannot go from {cur['state']} to rolled_back")
    if cur["state"] in ("proposed", "approved"):
        return _set(ws, rid, "rolled_back", actor, "discarded before anything was applied")   # no file is touched
    kind, where = codefix.target(_job_repo(ws, cur))
    note = ""
    if kind == "local":
        try:
            codefix.apply_local(where, cur["patch"], reverse=True)       # refuses if the files were edited since
        except codefix.FixError as e:
            raise ValueError(str(e)) from None
        note = "restored the original lines in the folder"
    else:
        note = ("the pull request is on GitHub: close it there to withdraw the change"
                if cur.get("applied") else "nothing had been sent to GitHub")
    out = _set(ws, rid, "rolled_back", actor, note)
    # a finding another applied remediation still fixes stays fixed
    held: set[str] = set()
    for other in list_(ws):
        if other["id"] != rid and other["kind"] == "code" and other["state"] in ("executed", "verified") \
                and other.get("job") == cur.get("job"):
            held |= set(other["finding_ids"])
    codescan.set_applied(ws, [i for i in cur["finding_ids"] if i not in held], False, cur.get("job"))
    return out
