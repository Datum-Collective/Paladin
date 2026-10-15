"""HTTP surface for the fixing agent: one streamed run per request, over the active workspace's latest scan."""
import asyncio
import contextvars
import json
import queue
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import auth, fixagent, harness, keys, mitre
from .ratelimit import RateLimit

router = APIRouter()
_limit = RateLimit(12, 600)
_running: set[int] = set()
_running_lock = threading.Lock()
SEVERITY = {"critical": 0, "high": 1, "medium": 2, "low": 3}
COMMIT_VERDICTS = ("verified", "fixed_untested", "partial")


class FixBody(BaseModel):
    job_id: int | None = Field(default=None, ge=1)
    finding_ids: list[str] | None = Field(default=None, max_length=40)
    instruction: str = Field(default="", max_length=2000)
    model: str = Field(default=fixagent.DEFAULT_MODEL, min_length=1, max_length=128)


def open_findings(job: dict) -> list[dict]:
    return [f for f in job.get("findings", []) if isinstance(f, dict) and not f.get("fixed")
            and f.get("exploitable") is not False]


def _targets(job: dict, ids: list[str] | None) -> list[dict]:
    pool = open_findings(job)
    if ids:
        want = set(ids)
        pool = [f for f in pool if f.get("id") in want]
    pool.sort(key=lambda f: (SEVERITY.get(str(f.get("severity", "")).lower(), 4), f.get("file", ""), f.get("line", 0)))
    return pool[:fixagent.MAX_TARGETS]


def _commit(ws: int, job: dict, targets: list[dict], result: dict) -> bool:
    """Record an evidence-backed result on the scan's local branch, as the scan's own fixes are. Never pushes."""
    root = harness.data_root() / str(job["id"]) / "repo"
    if result["verdict"] not in COMMIT_VERDICTS or not result["changed_files"]:
        return False
    if harness._git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root).strip() in ("HEAD", "main", "master") \
            or not job.get("branch"):
        harness._git(["checkout", "-q", "-B", f"apc/agent-{job['id']}-{int(time.time())}"], cwd=root)
    harness._git(["add", "-A"], cwd=root)
    harness._git(["-c", f"user.name={harness.AUTHOR[0]}", "-c", f"user.email={harness.AUTHOR[1]}", "commit", "-q",
                  "-m", (f"Paladin agent: fix {len(result['resolved'])} finding(s)" if targets else
                         f"Paladin agent: {result.get('instruction', '')[:60]}") + f" ({result['verdict']})"], cwd=root)
    base = harness._git(["rev-list", "--max-parents=0", "HEAD"], cwd=root).split()[0]
    branch = harness._git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root).strip()
    diff = harness._git(["diff", base, "HEAD"], cwd=root)
    tests = (result["tests"] or {}).get("after") or {}
    done = {r["id"] for r in result["resolved"]}
    fixes = [x for x in job.get("fixes", []) if isinstance(x, dict) and x.get("id") not in done]
    for t in targets:
        if t["id"] not in done:
            continue
        how = next(r["how"] for r in result["resolved"] if r["id"] == t["id"])
        fixes.append({"id": t["id"], "file": t["file"], "line": t["line"], "rule": t["rule"], "cwe": t.get("cwe"),
                      "technique": t.get("technique"), "method": "agent",
                      "explanation": (result["agent_claim"] or "Fixed by Paladin's agent")[:300],
                      "checks": [{"name": f"re-scan: {how}", "passed": True},
                                 {"name": "no new findings introduced", "passed": not result["regressions"]},
                                 {"name": f"tests passed ({tests.get('runner')})" if tests.get("ran")
                                  else "tests not run: " + str(tests.get("reason", "")),
                                  "passed": True if tests.get("ran") and tests.get("passed") else None},
                                 {"name": "MITRE citations exist: " + ", ".join(result["grounding"]["citations"][:6]),
                                  "passed": result["grounding"]["ok"]}]})
    findings = [{**f, "fixed": True} if isinstance(f, dict) and f.get("id") in done else f for f in job["findings"]]
    harness._upd(job["id"], state="ready", branch=branch, diff=diff[:400_000], fixes=json.dumps(fixes),
                 findings=json.dumps(findings))
    return True


def _record(job: dict, result: dict) -> None:
    rep = job["report"] if isinstance(job.get("report"), dict) else {}
    rep["agent_runs"] = (rep.get("agent_runs") or [])[-4:] + [{k: v for k, v in result.items() if k != "diff"}]
    harness._upd(job["id"], report=json.dumps(rep))
    harness._log(job["id"], f"agent ({result.get('model')}): {result['verdict']}: {result['reason']}"[:300])


def run_job(ws: int, job_id: int | None, ids, instruction: str, model: str, emit, cancelled, *, runner=None) -> dict:
    jobs = harness.list_jobs(ws) if job_id is None else [{"id": job_id}]
    if not jobs:
        raise LookupError("Scan a repository first: the agent works on a scan's working copy.")
    job = harness.get(ws, jobs[0]["id"])
    if job["state"] not in ("ready", "done", "pr_opened"):
        raise LookupError(f"The scan is {job['state']}. Wait for it to finish.")
    root = (harness.data_root() / str(job["id"]) / "repo").resolve()
    if not (root / ".git").exists():
        raise LookupError("This scan's working copy was cleared. Scan the repository again.")
    targets = _targets(job, ids)
    if not targets and not instruction.strip():
        raise LookupError("There are no open findings. Ask for a specific change instead.")
    emit({"type": "start", "job": job["id"], "repo": job["repo_url"], "model": model, "root": str(root),
          "targets": [{"id": t["id"], "file": t["file"], "line": t["line"], "rule": t["rule"], "cwe": t.get("cwe"),
                       "title": t.get("title")} for t in targets], "mitre": mitre.source()})
    result = fixagent.fix(root, targets, instruction=instruction, model=model, emit=emit, cancelled=cancelled,
                          **({"runner": runner} if runner else {}))
    result["job"], result["instruction"] = job["id"], instruction
    try:
        result["committed"] = _commit(ws, job, targets, result)
    except RuntimeError as e:
        result["committed"], result["commit_error"] = False, str(e)[:300]
    _record(harness.get(ws, job["id"]), result)
    return result


@router.post("/api/agent/fix")
async def agent_fix(b: FixBody, request: Request, u: dict = Depends(auth.require_user)):
    if not keys.configured("anthropic"):
        raise HTTPException(409, "The agent needs a Claude API key. Add one in Settings.")
    _limit.hit(f"agent:{u['user_id']}")
    ws = u["id"]
    with _running_lock:
        if ws in _running:
            raise HTTPException(409, "The agent is already working in this workspace.")
        _running.add(ws)
    q: queue.Queue = queue.Queue()
    cancelled = threading.Event()

    def work():
        try:
            res = run_job(ws, b.job_id, b.finding_ids, b.instruction.strip(), b.model, q.put, cancelled)
            q.put({"type": "verdict", **{k: v for k, v in res.items() if k != "steps"}})
        except LookupError as e:
            q.put({"type": "error", "kind": "precondition", "message": str(e)})
        except Exception as e:  # noqa: BLE001 - reported, never a stack trace or a key
            q.put({"type": "error", "kind": "server", "message": f"The agent failed: {type(e).__name__}"})
        finally:
            with _running_lock:
                _running.discard(ws)
            q.put(None)

    ctx = contextvars.copy_context()     # the run keeps this request's Supabase session and the user's key
    threading.Thread(target=ctx.run, args=(work,), daemon=True).start()

    async def gen():
        while True:
            try:
                ev = await asyncio.to_thread(q.get, True, 15)
            except queue.Empty:
                if await request.is_disconnected():
                    cancelled.set()
                    return
                yield ": keepalive\n\n"
                continue
            if ev is None:
                return
            if await request.is_disconnected():
                cancelled.set()
                return
            yield f"data: {json.dumps(ev, default=str)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/api/mitre/explain")
def mitre_explain(ids: str, u: dict = Depends(auth.require_user)):
    """Plain-language meaning of up to 40 MITRE codes (comma-separated). Unknown codes are reported, not guessed."""
    want = [i for i in dict.fromkeys(x.strip() for x in ids.split(",")) if i][:40]
    out = {}
    for i in want:
        e = mitre.explain(i)
        out[i] = e or {"id": i, "unknown": True, "summary": "Not an entry in Paladin's MITRE pack."}
    return {"codes": out, "source": mitre.source()}


@router.get("/api/agent/mitre/{ident}")
def mitre_entry(ident: str, u: dict = Depends(auth.require_user)):
    e = mitre.get(ident)
    if not e:
        raise HTTPException(404, "not a MITRE ATT&CK, CWE or CAPEC id in the pack")
    return e
