import asyncio
import json
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import analyze, auth, engine, inventory, store
from .models import Event
from .parsers.registry import PARSERS, parse_lines
from .remediation_api import router as remediation_router

MAX_BODY = 2_000_000
MAX_LINES = 2000
INGEST_RATE = (120, 60)  # requests per window seconds
_hits: dict[int, deque] = defaultdict(deque)


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.conn()
    auth.seed_demo()
    yield


app = FastAPI(title="Attack Path Compiler", lifespan=lifespan)
app.include_router(remediation_router)
origins = [o for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o]
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def guard(request: Request, call_next):
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


def _secure() -> bool:
    return os.environ.get("COOKIE_SECURE", "1") == "1"


class Creds(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)


class IngestBody(BaseModel):
    format: str = Field(default="json", max_length=32)
    lines: list[str] = Field(default=[], max_length=MAX_LINES)
    events: list[Event] = Field(default=[], max_length=MAX_LINES)


class FixBody(BaseModel):
    edges: list[str] = Field(max_length=50)


class KeyBody(BaseModel):
    label: str = Field(default="source", max_length=64)


@app.get("/health")
def health():
    return {"status": "ok"}


# ---- auth ----
@app.post("/api/auth/register")
def register(c: Creds, response: Response, request: Request):
    auth.register(c.email, c.password)
    return _login(c, response, request)


@app.post("/api/auth/login")
def login(c: Creds, response: Response, request: Request):
    return _login(c, response, request)


def _login(c: Creds, response: Response, request: Request):
    ip = request.client.host if request.client else "?"
    tok = auth.login(c.email, c.password, ip)
    response.set_cookie(auth.COOKIE, tok, httponly=True, samesite="lax", secure=_secure(),
                        max_age=auth.SESSION_TTL, path="/")
    return {"email": c.email.strip().lower()}


@app.post("/api/auth/demo")
def demo(response: Response, request: Request):
    """One-click sign-in to the seeded demo account; credentials stay server-side."""
    u, p = os.environ.get("DEMO_USER"), os.environ.get("DEMO_PASSWORD")
    if not (u and p):
        raise HTTPException(404, "demo account not configured")
    return _login(Creds(email=u, password=p), response, request)


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    auth.logout(request.cookies.get(auth.COOKIE))
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@app.get("/api/me")
def me(u: dict = Depends(auth.require_user)):
    return {"email": u["email"]}


# ---- ingest ----
def _normalize(ev: Event) -> Event:
    ips = inventory.load()["ips"]
    upd = {k: ips[getattr(ev, k)] for k in ("host", "dst") if getattr(ev, k) in ips}
    return ev.model_copy(update=upd) if upd else ev


def ingest_events(ws: int, events: list[Event]) -> int:
    """The ONE ingest path: HTTP upload, API key and Play all end up here."""
    return store.add_events(ws, [_normalize(e) for e in events])


def _rate(ws: int) -> None:
    now, d = time.time(), _hits[ws]
    while d and d[0] < now - INGEST_RATE[1]:
        d.popleft()
    if len(d) >= INGEST_RATE[0]:
        raise HTTPException(429, "rate limit")
    d.append(now)


@app.post("/api/ingest")
def ingest(b: IngestBody, u: dict = Depends(auth.user_or_key)):
    _rate(u["id"])
    bad: list[dict] = []
    if b.lines:
        if b.format not in PARSERS:
            raise HTTPException(422, f"unknown format; use one of {sorted(PARSERS)}")
        events, bad = parse_lines(b.format, b.lines)
    else:
        events = b.events
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


@app.post("/api/simulate/reset")
def sim_reset(u: dict = Depends(auth.require_user)):
    store.reset_workspace(u["id"])
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
        "risk": s["risk"], "severity": analyze.severity(s["risk"]), "events": s["events"],
    }


@app.get("/api/paths")
def paths(k: int = 10, u: dict = Depends(auth.require_user)):
    s = engine.snapshot(u["id"], k)
    return {"paths": s["paths"], "risk": s["risk"], "severity": analyze.severity(s["risk"])}


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
    valid = {e.id for e in inventory.load()["edges"]}
    if not b.edges or any(e not in valid for e in b.edges):
        raise HTTPException(422, "unknown edge id")
    store.apply_fix(u["id"], b.edges)
    s = engine.snapshot(u["id"])
    return {"risk": s["risk"], "severity": analyze.severity(s["risk"]), "applied": sorted(s["fixed"])}


@app.post("/api/keys")
def make_key(b: KeyBody, u: dict = Depends(auth.require_user)):
    return {"key": auth.create_key(u["id"], b.label)}


@app.get("/api/stream")
async def stream(request: Request, u: dict = Depends(auth.require_user)):
    ws = u["id"]

    async def gen():
        last = None
        while not await request.is_disconnected():
            ver = (store.event_count(ws), len(store.applied_fixes(ws)))
            if ver != last:
                last = ver
                s = await asyncio.to_thread(engine.snapshot, ws)
                yield f"data: {json.dumps({'events': ver[0], 'risk': s['risk'], 'severity': analyze.severity(s['risk'])})}\n\n"
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
            except Exception:
                return await super().get_response("index.html", scope)

    app.mount("/", SPA(directory=str(_static), html=True), name="ui")
