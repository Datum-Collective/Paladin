import asyncio
import hashlib
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import ai, analyze, auth, config as settings, keys, workspaces, codescan, engine, inventory, metrics, store, supa
from . import github_access
from .models import Event
from .ratelimit import RateLimit
from .parsers.registry import PARSERS, parse_lines
from . import harness
from .harness_api import router as harness_router
from .remediation_api import router as remediation_router
from .providers_api import router as providers_router
from .workspaces_api import router as workspaces_router
from .fixagent_api import router as fixagent_router

MAX_BODY = 2_000_000
MAX_LINES = 2000
INGEST_RATE = (120, 60)  # requests per window seconds
_ingest_limit = RateLimit(*INGEST_RATE)
_hits = _ingest_limit.hits
log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not settings.SUPABASE_ENABLED:
        log.warning("SUPABASE_URL / SUPABASE_ANON_KEY are not set: sign-in and all data endpoints will fail")
    yield
    supa.reset_client()   # the shared async client (http.py) lives as long as the process


app = FastAPI(title="Attack Path Compiler", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(github_access.router)
app.include_router(github_access.app_router)
app.include_router(remediation_router)
app.include_router(harness_router)
app.include_router(providers_router)
app.include_router(workspaces_router)
app.include_router(fixagent_router)
origins = [o for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o]
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(supa.DataError)
async def data_error(_: Request, e: supa.DataError):
    return JSONResponse({"detail": e.message}, status_code=e.status)


class BodyLimit:
    """Refuse request bodies over MAX_BODY as they stream in. A Content-Length check alone is bypassed by a chunked
    upload (no length header), which would let one request buffer an unbounded body in memory."""

    def __init__(self, app, max_bytes: int):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        seen, refused = 0, False

        async def limited_receive():
            nonlocal seen, refused
            if refused:
                return {"type": "http.disconnect"}
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > self.max_bytes:
                    refused = True
                    body = b'{"detail":"request too large"}'
                    await send({"type": "http.response.start", "status": 413, "headers": [
                        (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
                    await send({"type": "http.response.body", "body": body})
                    return {"type": "http.disconnect"}
            return msg

        async def guarded_send(msg):
            if not refused:     # the handler we cut off may still try to answer; the 413 already went out
                await send(msg)

        await self.app(scope, limited_receive, guarded_send)


# Registered before `guard`, so it runs inside it: guard still catches anything it raises
app.middleware("http")(auth.session_middleware)


@app.middleware("http")
async def guard(request: Request, call_next):
    if not auth.allowed_host(request):   # desktop: only the engine's own 127.0.0.1:<port> (DNS rebinding)
        return JSONResponse({"detail": "unknown host"}, status_code=421)
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > MAX_BODY:
        return JSONResponse({"detail": "request too large"}, status_code=413)
    try:
        resp = await call_next(request)
    except Exception:  # never leak stack traces
        return JSONResponse({"detail": "internal error"}, status_code=500)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp


app.add_middleware(BodyLimit, max_bytes=MAX_BODY)   # added last = outermost: nothing reads a body before it


class IngestBody(BaseModel):
    format: str = Field(default="json", max_length=32)
    lines: list[str] = Field(default=[], max_length=MAX_LINES)
    events: list[Event] = Field(default=[], max_length=MAX_LINES)


class FixBody(BaseModel):
    edges: list[str] = Field(max_length=50)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/config")
def config():
    """Public, non-secret capability flags the UI uses to pick its first screen."""
    desktop = auth.desktop_mode()
    return {"desktop": desktop, "auth": "github", "signin": settings.SUPABASE_ENABLED,
            # names only, never values: lets the login screen tell a developer what to set
            "signin_missing": [n for n, v in (("SUPABASE_URL", settings.SUPABASE_URL),
                                              ("SUPABASE_ANON_KEY", settings.SUPABASE_ANON_KEY)) if not v],
            "ai": ai.enabled(),
            # web: our GitHub App (per-user installations); desktop: the user's own token from the keychain
            "github": keys.configured("github") if desktop else github_access.app_enabled(),
            "github_mode": "token" if desktop else "app",
            "providers": keys.status(),
            "scans": not settings.SERVERLESS,
            "version": os.environ.get("APP_VERSION", "dev")}


# ---- auth: see auth.py (GitHub through Supabase; no passwords, no shared demo account) ----


# ---- ingest ----
def _normalize(ev: Event) -> Event:
    ips = inventory.load()["ips"]
    upd = {k: ips[getattr(ev, k)] for k in ("host", "dst") if getattr(ev, k) in ips}
    return ev.model_copy(update=upd) if upd else ev


def ingest_events(ws: int, events: list[Event]) -> int:
    """The ONE ingest path: HTTP upload, API key and Play all end up here."""
    t0 = time.perf_counter()
    n = store.add_events(ws, [_normalize(e) for e in events])
    metrics.record_ingest(n, (time.perf_counter() - t0) * 1000)
    return n


def _rate(key: str) -> None:
    _ingest_limit.limit, _ingest_limit.window_s = INGEST_RATE   # read per call: tests and operators may retune it
    _ingest_limit.hit(key)


@app.post("/api/ingest")
def ingest(b: IngestBody, u: dict = Depends(auth.user_or_key)):
    # per account (or per key): switching or multiplying workspaces must not multiply the budget
    _rate(u["user_id"] or "key:" + hashlib.sha256(u["api_key"].encode()).hexdigest())
    bad: list[dict] = []
    if b.lines:
        if b.format not in PARSERS:
            raise HTTPException(422, f"unknown format; use one of {sorted(PARSERS)}")
        events, bad = parse_lines(b.format, b.lines)
    else:
        events = b.events
    if u.get("api_key"):
        t0 = time.perf_counter()
        try:
            out = store.ingest_with_key(u["api_key"], [_normalize(e) for e in events])
        except supa.DataError as e:
            raise HTTPException(401 if e.status in (400, 401, 404) else e.status, "invalid API key") from None
        n = out.get("accepted", 0)
        metrics.record_ingest(n, (time.perf_counter() - t0) * 1000)
    else:
        n = ingest_events(u["id"], events)
    return {"accepted": n, "rejected": len(bad), "errors": bad[:10]}


# ---- simulate (replays data/samples through ingest_events) ----
_sample_cache: list[Event] | None = None


def _samples() -> list[Event]:
    global _sample_cache
    if _sample_cache is None:
        d = inventory.seed_dir() / "samples"
        out: list[Event] = []
        mf = d / "manifest.json"
        if mf.exists():
            for item in json.loads(mf.read_text()):
                ev, _ = parse_lines(item["format"], (d / item["file"]).read_text().splitlines())
                out.extend(ev)
        _sample_cache = sorted(out, key=lambda e: e.ts)
    return _sample_cache


@app.post("/api/simulate/start")
def sim_start(u: dict = Depends(auth.require_user)):
    store.reset_workspace(u["id"])
    return _sim_step(u["id"], 25)


@app.post("/api/simulate/step")
def sim_step(n: int = 25, u: dict = Depends(auth.require_user)):
    return _sim_step(u["id"], max(1, min(n, 500)))


def _sim_step(ws: int, n: int):
    s, pos = _samples(), store.sim_pos(ws)
    batch = s[pos:pos + n]
    ingest_events(ws, batch)
    store.set_sim_pos(ws, pos + len(batch))
    return {"position": pos + len(batch), "total": len(s), "done": pos + len(batch) >= len(s)}


@app.get("/api/simulate/status")
def sim_status(u: dict = Depends(auth.require_user)):
    return {"total": len(_samples()), "position": store.sim_pos(u["id"])}


@app.get("/api/events")
def events(limit: int = 100, u: dict = Depends(auth.require_user)):
    limit = max(1, min(limit, 500))
    evs = store.get_events(u["id"])
    return {"total": len(evs), "events": [e.model_dump(exclude={"raw"}) | {"raw": e.raw[:240]}
                                          for e in reversed(evs[-limit:])]}


@app.post("/api/simulate/reset")
def sim_reset(u: dict = Depends(auth.require_user)):
    harness.wipe(u["id"])
    store.wipe_workspace(u["id"])
    return {"ok": True}


# ---- analysis ----
def _node(n):
    return n.model_dump()


@app.get("/api/graph")
def graph(u: dict = Depends(auth.require_user)):
    s = engine.snapshot(u["id"])
    return {
        "nodes": [_node(n) for n in s["nodes"]],
        "edges": [{**e.model_dump(exclude={"match"}), "fixed": e.id in s["fixed"]} for e in s["edges"]],
        "risk": s["risk"], "worst": analyze.worst_risk(s["paths"]),
        "severity": analyze.severity(analyze.worst_risk(s["paths"])), "events": s["events"],
    }


@app.get("/api/paths")
def paths(k: int = 10, u: dict = Depends(auth.require_user)):
    s = engine.snapshot(u["id"], k)
    w = analyze.worst_risk(s["paths"])
    return {"paths": s["paths"], "risk": s["risk"], "worst": w, "severity": analyze.severity(w)}


@app.get("/api/paths/{pid}")
def path_detail(pid: str, u: dict = Depends(auth.require_user)):
    for p in engine.snapshot(u["id"], analyze.MAX_K)["paths"]:
        if p["id"] == pid:
            return p
    raise HTTPException(404, "path not found")


@app.get("/api/fixes")
def get_fixes(u: dict = Depends(auth.require_user)):
    return engine.fixes(engine.snapshot(u["id"], analyze.MAX_K))


@app.post("/api/fixes/apply")
def apply_fix(b: FixBody, u: dict = Depends(auth.require_user)):
    valid = {e.id for e in engine.workspace_model(u["id"])[1]}
    if not b.edges or any(e not in valid for e in b.edges):
        raise HTTPException(422, "unknown edge id")
    store.apply_fix(u["id"], b.edges)
    s = engine.snapshot(u["id"])
    w = analyze.worst_risk(s["paths"])
    return {"risk": s["risk"], "worst": w, "severity": analyze.severity(w), "applied": sorted(s["fixed"])}


class ScanBody(BaseModel):
    repo: str = Field(default="uploaded", max_length=120)
    files: list[dict] = Field(max_length=codescan.MAX_FILES * 3)


@app.post("/api/codescan")
def code_scan(b: ScanBody, u: dict = Depends(auth.require_user)):
    _rate(u["user_id"])
    return codescan.run(u["id"], b.repo, b.files)


@app.get("/api/codescan")
def code_report(u: dict = Depends(auth.require_user)):
    return codescan.report(u["id"])


@app.delete("/api/codescan")
def code_clear(u: dict = Depends(auth.require_user)):
    codescan.clear(u["id"])
    return {"ok": True}


@app.get("/api/metrics")
def get_metrics(u: dict = Depends(auth.require_user)):
    s = engine.snapshot(u["id"])
    return {**metrics.summary(), "compression": engine.compression(s), "current_analysis_ms": s["timings"]}


@app.get("/api/timeline")
def get_timeline(u: dict = Depends(auth.require_user)):
    return {**engine.timeline(u["id"]), "risk_series": engine.risk_series(u["id"])}


@app.get("/api/benchmarks")
def get_benchmarks(u: dict = Depends(auth.require_user)):
    p = inventory.seed_dir() / "benchmarks.json"
    return json.loads(p.read_text()) if p.exists() else {"runs": []}


@app.get("/api/stream")
async def stream(request: Request, u: dict = Depends(auth.require_user)):
    ws = u["id"]

    async def gen():
        last = None
        tick, code_ver = 0, None
        while not await request.is_disconnected():
            try:   # Supabase calls block: off the event loop (the thread inherits this request's session)
                if tick % 4 == 0:   # scans change slowly: check them every 2 s, the live counters every 0.5 s
                    def scan_sig():
                        j = supa.select("jobs", {"ws": supa.eq(ws)}, columns="id,state", order="id.desc", limit=1)
                        return (codescan.version(ws), j[0]["id"] if j else 0, j[0]["state"] if j else "")
                    code_ver = await asyncio.to_thread(scan_sig)
                tick += 1
                ver = await asyncio.to_thread(lambda: (store.event_count(ws), len(store.applied_fixes(ws)), code_ver))
            except supa.DataError:
                return   # e.g. the session expired: the browser reconnects, and the reconnect refreshes it
            if ver != last:
                last = ver
                s = await asyncio.to_thread(engine.snapshot, ws)
                yield f"data: {json.dumps({'events': ver[0], 'risk': s['risk'], 'severity': analyze.severity(analyze.worst_risk(s['paths']))})}\n\n"
            else:
                yield ": keepalive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---- static UI, mounted LAST ----
_static = Path(os.environ.get("STATIC_DIR", ""))
if os.environ.get("STATIC_DIR") and _static.is_dir():
    class SPA(StaticFiles):
        async def get_response(self, path, scope):
            try:
                return await super().get_response(path, scope)
            except StarletteHTTPException as e:
                # client-side routes get the app shell; a missing API route or file stays a real 404, and any
                # other failure is not hidden behind a 200 page
                route = path.replace("\\", "/")   # Starlette passes OS separators: api\x on Windows
                if e.status_code != 404 or route == "api" or route.startswith("api/"):
                    raise
                return await super().get_response("index.html", scope)

    app.mount("/", SPA(directory=str(_static), html=True), name="ui")
