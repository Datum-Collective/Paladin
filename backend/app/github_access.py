"""Per-user GitHub repo access: our GitHub App on the web, the user's own token on the desktop.

Threat model (web): every caller may be a bug-bounty tester trying to reach someone else's repos.

- An installation is linked to a user only after a GitHub user token proves that the GitHub account this user
  signed in with owns it (`callback`). `installation_id` from the URL is never trusted on its own.
- Every repo-scoped endpoint takes `authorized_repo` as a dependency, and scans and pull requests go through the
  same `resolve_repo`. It looks the installation up in OUR table filtered by the current user and checks the repo
  is in that installation; anything else is a 404. It never asks GitHub "which installation has this repo".
- Installation tokens are minted per repo, so a logic bug still can't reach another repo. Scans get a read-only one.
- Writes are a fixed allowlist (commit to the `fixes` branch fast-forward only, open or reuse one PR), audited
  before they happen, rate-limited per user.

Desktop: one person on their own machine with their own token (OS keychain). The same write rules apply.
"""
import asyncio
import base64
import hashlib
import logging
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from . import auth, config, db, harness, keys, supa
from . import github_app as gh
from .http import client
from .ratelimit import RateLimit

log = logging.getLogger("uvicorn.error")

STATE_TTL = timedelta(minutes=10)
REPO_CACHE_TTL_S = 60
FIXES_BRANCH = "fixes"
MAX_FILE_BYTES = 1_000_000

OWNER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
REPO_RE = re.compile(r"[A-Za-z0-9._-]{1,100}")
INSTALLATION_ID_RE = re.compile(r"[0-9]{1,19}")
REF_RE = re.compile(r"[A-Za-z0-9._/-]{1,200}")
PATH_SEGMENT_RE = re.compile(r"[A-Za-z0-9._ +@()-]{1,255}")


def app_enabled() -> bool:
    return config.GITHUB_ENABLED and not config.desktop_mode()


def _require_enabled():
    if not app_enabled():
        raise HTTPException(503, "GitHub integration is not configured")


router = APIRouter(prefix="/api/github", tags=["github"])
app_router = APIRouter(prefix="/api/github", tags=["github"], dependencies=[Depends(_require_enabled)])
_write_limit = RateLimit(limit=10, window_s=60)

# installation_id -> (fetched_at monotonic, repos)
_repo_cache: dict[int, tuple[float, list[dict]]] = {}


def _not_found(what: str = "Not found") -> HTTPException:
    return HTTPException(404, what)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _iso(dt: datetime) -> str:
    # No "+00:00": a literal '+' in a PostgREST filter can be read as a space
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _manage_url(installation_id: int) -> str:
    # Installations are always on personal accounts (enforced in `callback`)
    return f"https://github.com/settings/installations/{installation_id}"


def _blocked(login: str) -> bool:
    return login.lower() in config.GITHUB_BLOCKED_ACCOUNTS


# --- Ownership: the only ways an installation or repo is resolved for a request ---

async def _linked_installations(user_id: str) -> list[dict]:
    rows = await db.select("github_installations", {
        "select": "installation_id,github_account_login,created_at",
        "user_id": f"eq.{user_id}",
        "order": "created_at.asc",
    })
    return [r for r in rows if not _blocked(r["github_account_login"])]


async def owned_installation(installation_id: str, user: dict = Depends(auth.current_claims)) -> dict:
    if not INSTALLATION_ID_RE.fullmatch(installation_id):
        raise _not_found()
    for row in await _linked_installations(user["sub"]):
        if row["installation_id"] == int(installation_id):
            return row
    raise _not_found()


async def _installation_repos(installation_id: int) -> list[dict]:
    cached = _repo_cache.get(installation_id)
    if cached and time.monotonic() - cached[0] < REPO_CACHE_TTL_S:
        return cached[1]
    raw = await gh.paginate_installation("/installation/repositories", "repositories",
                                         installation_id=installation_id)
    repos = [{
        "id": r["id"],
        "full_name": r["full_name"],
        "name": r["name"],
        "owner": r["owner"]["login"],
        "private": r["private"],
        "default_branch": r["default_branch"],
        "description": r.get("description"),
    } for r in raw]
    _repo_cache[installation_id] = (time.monotonic(), repos)
    return repos


def _forget(installation_id: int):
    _repo_cache.pop(installation_id, None)
    gh.forget_installation(installation_id)


@dataclass(frozen=True)
class RepoCtx:
    user_id: str
    installation_id: int | None
    repo_id: int
    full_name: str        # canonical, from GitHub; used to build every API path
    default_branch: str
    private: bool = True
    via: str = "app"      # "app": GitHub App installation token (web); "token": the user's own token (desktop)


def _valid_name(owner: str, repo: str) -> bool:
    return bool(OWNER_RE.fullmatch(owner) and REPO_RE.fullmatch(repo) and repo not in (".", "..")
                and not _blocked(owner))


async def resolve_repo(user_id: str, owner: str, repo: str) -> RepoCtx | None:
    """The repo if it is in an installation linked to THIS user, else None."""
    if not app_enabled() or not _valid_name(owner, repo):
        return None
    wanted = f"{owner}/{repo}".lower()
    for inst in await _linked_installations(user_id):
        try:
            repos = await _installation_repos(inst["installation_id"])
        except gh.GitHubError as e:
            log.warning("Listing repos for installation %s failed: %s", inst["installation_id"], e)
            continue
        for r in repos:
            if r["full_name"].lower() == wanted:
                return RepoCtx(user_id, inst["installation_id"], r["id"], r["full_name"], r["default_branch"],
                               r["private"])
    return None


async def authorized_repo(owner: str, repo: str, user: dict = Depends(auth.current_claims)) -> RepoCtx:
    """The single gate for every repo-scoped endpoint. 404 unless the repo is in an installation
    linked to the CURRENT user."""
    ctx = await resolve_repo(user["sub"], owner, repo)
    if ctx is None:
        raise _not_found("Repository not found")
    return ctx


# --- desktop: the user's own token ---

def _pat_headers() -> dict:
    tok = keys.get("GITHUB_TOKEN")
    if not tok:
        raise HTTPException(409, "Add a GitHub token in Settings to open pull requests, or download the patch.")
    return {**gh._API_HEADERS, "Authorization": f"Bearer {tok}"}


async def _token_repo(user_id: str, owner: str, repo: str) -> RepoCtx:
    if not _valid_name(owner, repo):
        raise _not_found("Repository not found")
    r = await client.get(f"{gh.API}/repos/{owner}/{repo}", headers=_pat_headers())
    if r.status_code != 200:
        raise _not_found("Repository not found")
    d = r.json()
    if not (d.get("permissions") or {}).get("push"):
        raise HTTPException(409, f"Your GitHub token can't push to {d.get('full_name', f'{owner}/{repo}')}: the account "
                                 "it belongs to has no write access there. Ask the owner to add you as a collaborator, "
                                 "or fork it and scan your fork. Download the patch to use the fixes now.")
    return RepoCtx(user_id, None, d["id"], d["full_name"], d["default_branch"], bool(d.get("private")), via="token")


async def _call(ctx: RepoCtx, method: str, path: str, **kw) -> httpx.Response:
    """GitHub call scoped to ctx's repo. `path` is relative to /repos/{full_name}."""
    if ctx.via == "token":
        return await client.request(method, f"{gh.API}/repos/{ctx.full_name}{path}", headers=_pat_headers(), **kw)
    return await gh.as_installation(method, f"/repos/{ctx.full_name}{path}",
                                    installation_id=ctx.installation_id, repo_id=ctx.repo_id, **kw)


def _upstream_error(what: str, r: httpx.Response) -> HTTPException:
    log.warning("GitHub %s failed: %s %s", what, r.status_code, gh._message(r))
    return HTTPException(502, "GitHub request failed")


# --- Install / link flow ---

@app_router.get("/install-url")
async def install_url(user: dict = Depends(auth.current_claims)):
    state = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    await db.delete("github_install_states", {"user_id": f"eq.{user['sub']}", "expires_at": f"lt.{_iso(now)}"})
    await db.insert("github_install_states", {
        "state_hash": _hash(state),
        "user_id": user["sub"],
        "expires_at": _iso(now + STATE_TTL),
    })
    params = httpx.QueryParams(state=state)
    return {"url": f"https://github.com/apps/{config.GITHUB_APP_SLUG}/installations/new?{params}"}


@app_router.get("/callback")
async def callback(request: Request, code: str | None = None, installation_id: str | None = None,
                   setup_action: str | None = None, state: str | None = None):
    log.info("GitHub install callback received params: %s", sorted(request.query_params))

    def fail(reason: str, **details) -> RedirectResponse:
        log.warning("GitHub connect failed: %s %s", reason, details)
        return RedirectResponse("/?github_error=1", status_code=302)

    try:
        user = await auth.current_claims(request)
    except HTTPException:
        return fail("not signed in to the app")
    uid = user["sub"]

    # 1. Single-use state bound to this user. The delete is atomic: a replay gets nothing back.
    if not state:
        return fail("missing state", user_id=uid)
    consumed = await db.delete("github_install_states", {
        "state_hash": f"eq.{_hash(state)}",
        "user_id": f"eq.{uid}",
        "expires_at": f"gt.{_iso(datetime.now(timezone.utc))}",
    })
    if not consumed:
        return fail("state unknown, expired, already used, or another user's", user_id=uid)

    if setup_action == "request":
        return fail("installation is waiting for an org owner's approval", user_id=uid)
    if not code:
        return fail("missing code", user_id=uid)
    if not installation_id or not INSTALLATION_ID_RE.fullmatch(installation_id):
        return fail("missing or malformed installation_id", user_id=uid)
    claimed = int(installation_id)

    # 2. The GitHub account this user signed in to OUR app with (not user_metadata: user-editable)
    expected_github_id = await db.github_user_id(uid)
    if expected_github_id is None:
        return fail("no GitHub identity on this Supabase user", user_id=uid)

    # 3. Prove ownership with a user token, then throw the token away
    try:
        user_token = await gh.exchange_code(code)
    except (gh.GitHubError, httpx.HTTPError) as e:
        return fail("code exchange failed", user_id=uid, error=str(e))
    try:
        me = await gh.as_user(user_token, "/user")
        if me.status_code != 200:
            return fail("GET /user failed", user_id=uid, status=me.status_code)
        github_user = me.json()
        installs = await gh.user_installations(user_token)
    except (gh.GitHubError, httpx.HTTPError) as e:
        return fail("listing user installations failed", user_id=uid, error=str(e))
    finally:
        await gh.revoke_user_token(user_token)
        del user_token

    if github_user.get("id") != expected_github_id:
        return fail("github.com account differs from the account signed in to the app",
                    user_id=uid, github_login=github_user.get("login"))
    inst = next((i for i in installs if i.get("id") == claimed), None)
    if inst is None:
        return fail("installation_id not in this user's /user/installations", user_id=uid, installation_id=claimed)
    account = inst.get("account") or {}
    if str(inst.get("app_id")) != config.GITHUB_APP_ID:
        return fail("installation belongs to a different app", user_id=uid, installation_id=claimed)
    if account.get("type") != "User" or account.get("id") != expected_github_id:
        return fail("only personal-account installations owned by this user can be linked",
                    user_id=uid, installation_id=claimed, account=account.get("login"))
    if _blocked(account.get("login", "")):
        return fail("installation is on a blocked account", user_id=uid, account=account.get("login"))

    # 4. Link (re-linking the same installation is a no-op; another user's link is a conflict)
    try:
        await db.insert_ignore_duplicate("github_installations", {
            "user_id": uid,
            "installation_id": claimed,
            "github_account_login": account["login"],
        }, on_conflict="user_id,installation_id")
    except httpx.HTTPStatusError as e:
        return fail("saving link failed", user_id=uid, installation_id=claimed, status=e.response.status_code)
    _forget(claimed)
    log.info("Linked GitHub installation %s (%s) to user %s", claimed, account["login"], uid)
    return RedirectResponse("/?github_connected=1", status_code=302)


# --- Read endpoints ---

@app_router.get("/installations")
async def list_installations(user: dict = Depends(auth.current_claims)):
    return [{
        "installation_id": row["installation_id"],
        "account": row["github_account_login"],
        "created_at": row["created_at"],
        "manage_url": _manage_url(row["installation_id"]),
    } for row in await _linked_installations(user["sub"])]


def _public_repo(r: dict) -> dict:
    return {"full_name": r["full_name"], "owner": r["owner"], "name": r["name"], "private": r["private"],
            "default_branch": r["default_branch"], "description": r.get("description"),
            "html_url": f"https://github.com/{r['full_name']}"}


@app_router.get("/repos")
async def list_repos(user: dict = Depends(auth.current_claims)):
    out = []
    for inst in await _linked_installations(user["sub"]):
        entry = {"installation_id": inst["installation_id"], "account": inst["github_account_login"],
                 "manage_url": _manage_url(inst["installation_id"])}
        try:
            entry["repos"] = [_public_repo(r) for r in await _installation_repos(inst["installation_id"])]
        except gh.GitHubError as e:
            log.warning("Listing repos for installation %s failed: %s", inst["installation_id"], e)
            entry["repos"] = []
            entry["error"] = "unavailable"  # e.g. uninstalled on GitHub
        out.append(entry)
    return out


@app_router.get("/manage-url/{installation_id}")
async def manage_url(inst: dict = Depends(owned_installation)):
    return {"url": _manage_url(inst["installation_id"])}


@app_router.delete("/installations/{installation_id}")
async def unlink(inst: dict = Depends(owned_installation), user: dict = Depends(auth.current_claims)):
    await db.delete("github_installations", {
        "user_id": f"eq.{user['sub']}",
        "installation_id": f"eq.{inst['installation_id']}",
    })
    _forget(inst["installation_id"])
    return {
        "unlinked": True,
        "uninstall_url": _manage_url(inst["installation_id"]),
        "message": "Disconnected from this app. To fully revoke access, uninstall the app on GitHub.",
    }


def _validate_ref(ref: str | None, default: str) -> str:
    ref = ref or default
    if not REF_RE.fullmatch(ref) or ".." in ref or ref.startswith("/") or ref.endswith("/"):
        raise HTTPException(422, "Invalid ref")
    return ref


def _validate_path(path: str, *, for_write: bool = False) -> str:
    segments = path.split("/")
    if len(path) > 1000 or not all(PATH_SEGMENT_RE.fullmatch(s) and s not in (".", "..") for s in segments):
        raise HTTPException(422, "Invalid path")
    if for_write:
        lowered = path.lower()
        if segments[0].lower() == ".git" or lowered.startswith(".github/workflows/"):
            raise HTTPException(422, "Writing to this path is not allowed")
    return path


@app_router.get("/repos/{owner}/{repo}/tree")
async def repo_tree(ref: str | None = None, ctx: RepoCtx = Depends(authorized_repo)):
    ref = _validate_ref(ref, ctx.default_branch)
    r = await _call(ctx, "GET", f"/git/trees/{quote(ref, safe='')}", params={"recursive": "1"})
    if r.status_code in (404, 409, 422):
        raise _not_found("Ref not found")
    if r.status_code != 200:
        raise _upstream_error("tree", r)
    data = r.json()
    return {
        "ref": ref,
        "truncated": data.get("truncated", False),
        "entries": [{"path": e["path"], "type": e["type"], "size": e.get("size")} for e in data["tree"][:10000]],
    }


@app_router.get("/repos/{owner}/{repo}/file")
async def repo_file(path: str, ref: str | None = None, ctx: RepoCtx = Depends(authorized_repo)):
    path = _validate_path(path)
    ref = _validate_ref(ref, ctx.default_branch)
    r = await _call(ctx, "GET", f"/contents/{quote(path)}", params={"ref": ref})
    if r.status_code == 404:
        raise _not_found("File not found")
    if r.status_code != 200:
        raise _upstream_error("contents", r)
    data = r.json()
    if not isinstance(data, dict) or data.get("type") != "file":
        raise HTTPException(422, "Path is not a file")
    if data.get("size", 0) > MAX_FILE_BYTES or data.get("encoding") != "base64":
        raise HTTPException(413, "File too large")
    raw = base64.b64decode(data["content"])
    try:
        text, binary = raw.decode("utf-8"), False
    except UnicodeDecodeError:
        text, binary = None, True
    return {"path": data["path"], "ref": ref, "sha": data["sha"], "size": data["size"],
            "binary": binary, "content": text}


# --- Writes: the allowlist is "commit files to the fixes branch, open/reuse one PR" ---

class FileChange(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    content: str = Field(max_length=500_000)


class FixRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=10_000)
    commit_message: str = Field(min_length=1, max_length=500)
    files: list[FileChange] = Field(min_length=1, max_length=25)


async def _audit(ctx: RepoCtx, action: str, detail: dict, status: str) -> None:
    """Append-only. The 'attempted' row is written BEFORE the GitHub write; if it fails, the write never happens."""
    row = {"user_id": ctx.user_id, "installation_id": ctx.installation_id, "repo": ctx.full_name,
           "action": action, "detail": {**detail, "status": status}, "via": ctx.via}
    if ctx.via == "app":
        await db.insert("github_audit_log", row)
    else:   # desktop: no service key; RLS lets a user append their own token-made rows only
        await asyncio.to_thread(supa.insert, "github_audit_log", row, returning=None)


async def _audited(ctx: RepoCtx, action: str, detail: dict, ok_status: int, method: str, path: str, **kw):
    await _audit(ctx, action, detail, "attempted")
    r = await _call(ctx, method, path, **kw)
    try:
        await _audit(ctx, action, detail, "ok" if r.status_code == ok_status else "failed")
    except Exception as e:  # noqa: BLE001 - the write already happened; never hide its result from the caller
        log.error("Audit result row for %s on %s failed: %s", action, ctx.full_name, e)
    return r


async def _write_rate_limit(user: dict = Depends(auth.current_claims)):
    _write_limit.hit(f"user:{user['sub']}")


async def _ref_sha(ctx: RepoCtx, branch: str) -> str | None:
    r = await _call(ctx, "GET", f"/git/ref/heads/{quote(branch, safe='')}")
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise _upstream_error("get ref", r)
    return r.json()["object"]["sha"]


async def commit_fix(ctx: RepoCtx, fix: FixRequest) -> dict:
    """Commit `files` on top of the `fixes` branch (created from the default branch if missing) and open a PR
    fixes -> default branch, or reuse the open one. Fast-forward only: never force-pushes, never touches the
    default branch, never deletes anything."""
    paths = [_validate_path(f.path, for_write=True) for f in fix.files]
    if len(set(paths)) != len(paths):
        raise HTTPException(422, "Duplicate paths")
    if sum(len(f.content.encode()) for f in fix.files) > 2 * MAX_FILE_BYTES:
        raise HTTPException(413, "Fix too large")
    if ctx.default_branch == FIXES_BRANCH:
        raise HTTPException(409, f"Default branch is '{FIXES_BRANCH}'; refusing to commit to it")

    # 1. Ensure the fixes branch exists
    base_sha = await _ref_sha(ctx, FIXES_BRANCH)
    if base_sha is None:
        base_sha = await _ref_sha(ctx, ctx.default_branch)
        if base_sha is None:
            raise HTTPException(409, "Repository has no commits on its default branch")
        r = await _audited(ctx, "create_branch", {"branch": FIXES_BRANCH, "from": ctx.default_branch, "sha": base_sha},
                           201, "POST", "/git/refs", json={"ref": f"refs/heads/{FIXES_BRANCH}", "sha": base_sha})
        if r.status_code == 422:
            raise HTTPException(409, "The fixes branch was just created by another request; retry")
        if r.status_code != 201:
            raise _upstream_error("create branch", r)

    # 2. Commit on top of it
    r = await _call(ctx, "GET", f"/git/commits/{base_sha}")
    if r.status_code != 200:
        raise _upstream_error("get commit", r)
    base_tree = r.json()["tree"]["sha"]
    r = await _call(ctx, "POST", "/git/trees", json={
        "base_tree": base_tree,
        "tree": [{"path": f.path, "mode": "100644", "type": "blob", "content": f.content} for f in fix.files],
    })
    if r.status_code != 201:
        raise _upstream_error("create tree", r)
    r = await _call(ctx, "POST", "/git/commits",
                    json={"message": fix.commit_message, "tree": r.json()["sha"], "parents": [base_sha]})
    if r.status_code != 201:
        raise _upstream_error("create commit", r)
    commit_sha = r.json()["sha"]

    r = await _audited(ctx, "commit", {"branch": FIXES_BRANCH, "parent": base_sha, "commit": commit_sha,
                                       "paths": paths}, 200,
                       "PATCH", f"/git/refs/heads/{FIXES_BRANCH}", json={"sha": commit_sha, "force": False})
    if r.status_code == 422:
        raise HTTPException(409, "The fixes branch moved while committing; retry")
    if r.status_code != 200:
        raise _upstream_error("update branch", r)

    # 3. Reuse the open PR from fixes, or open one
    owner_login = ctx.full_name.split("/")[0]
    r = await _call(ctx, "GET", "/pulls", params={"head": f"{owner_login}:{FIXES_BRANCH}",
                                                  "base": ctx.default_branch, "state": "open"})
    if r.status_code != 200:
        raise _upstream_error("list pulls", r)
    existing = r.json()
    if existing:
        number, created = existing[0]["number"], False
    else:
        r = await _audited(ctx, "open_pr", {"head": FIXES_BRANCH, "base": ctx.default_branch, "title": fix.title},
                           201, "POST", "/pulls", json={"title": fix.title, "body": fix.body,
                                                        "head": FIXES_BRANCH, "base": ctx.default_branch})
        if r.status_code != 201:
            raise _upstream_error("open PR", r)
        number, created = r.json()["number"], True

    return {
        "branch": FIXES_BRANCH,
        "commit_sha": commit_sha,
        "pull_request": {"number": number, "created": created,
                         "html_url": f"https://github.com/{ctx.full_name}/pull/{number}"},
    }


# Route-level dependencies run first: the per-user rate limit applies before the repo check,
# so probing other users' repos through this endpoint is limited too.
@app_router.post("/repos/{owner}/{repo}/fixes", status_code=201, dependencies=[Depends(_write_rate_limit)])
async def apply_fix(fix: FixRequest, ctx: RepoCtx = Depends(authorized_repo)):
    return await commit_fix(ctx, fix)


# --- Used by scans (harness) and workspace import ---

async def open_job_pr(u: dict, jid: int) -> dict:
    """Send a ready scan's fixes as a pull request, through the same fixes-branch flow as POST .../fixes."""
    _write_limit.hit(f"user:{u['user_id']}")
    try:
        req = await asyncio.to_thread(harness.pr_request, u["id"], jid)
    except harness.JobNotFound:
        raise HTTPException(404, "job not found") from None
    except RuntimeError as e:
        raise HTTPException(409, str(e)[:200]) from None
    if config.desktop_mode():
        ctx = await _token_repo(u["user_id"], req["owner"], req["repo"])
    else:
        ctx = await resolve_repo(u["user_id"], req["owner"], req["repo"])
        if ctx is None:
            raise HTTPException(409, "Connect this repository through the GitHub App (Integrations) to open pull "
                                     "requests, or download the patch instead.")
    fix = FixRequest(title=req["title"], body=req["body"][:10_000], commit_message=req["commit_message"],
                     files=[FileChange(path=p, content=c) for p, c in req["files"].items()])
    out = await commit_fix(ctx, fix)
    return await asyncio.to_thread(harness.mark_pr_opened, u["id"], jid, out["pull_request"]["html_url"])


async def _fix_ctx(u: dict, repo_full: str) -> "RepoCtx":
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo_full or ""):
        raise HTTPException(409, "Pull requests are only available for GitHub repositories.")
    owner, repo = repo_full.split("/", 1)
    if config.desktop_mode():
        return await _token_repo(u["user_id"], owner, repo)
    ctx = await resolve_repo(u["user_id"], owner, repo)
    if ctx is None:
        raise HTTPException(409, "Connect this repository through the GitHub App (Integrations) to open pull "
                                 "requests, or download the patch instead.")
    return ctx


async def read_repo_files(u: dict, repo_full: str, paths: list[str]) -> dict[str, str | None]:
    """Current content of each file on the default branch; None where the file is gone."""
    ctx = await _fix_ctx(u, repo_full)
    out: dict[str, str | None] = {}
    for p in paths:
        r = await _call(ctx, "GET", f"/contents/{quote(_validate_path(p, for_write=False), safe='/')}",
                        params={"ref": ctx.default_branch})
        if r.status_code == 404:
            out[p] = None
            continue
        if r.status_code != 200:
            raise _upstream_error("read file", r)
        d = r.json()
        if not isinstance(d, dict) or d.get("encoding") != "base64":
            raise HTTPException(409, f"{p} is too large or not a regular file to patch safely.")
        out[p] = base64.b64decode(d["content"]).decode("utf-8", errors="strict")
    return out


async def pull_merged(u: dict, repo_full: str, number: int) -> bool:
    ctx = await _fix_ctx(u, repo_full)
    r = await _call(ctx, "GET", f"/pulls/{int(number)}")
    if r.status_code != 200:
        raise _upstream_error("read pull request", r)
    return bool(r.json().get("merged"))


async def open_fix_pr(u: dict, repo_full: str, title: str, body: str, commit_message: str, files: dict[str, str]) -> str:
    """Send exactly `files` as a pull request through the fixes-branch flow and return its URL."""
    _write_limit.hit(f"user:{u['user_id']}")
    ctx = await _fix_ctx(u, repo_full)
    fix = FixRequest(title=title[:200], body=body[:10_000], commit_message=commit_message[:500],
                     files=[FileChange(path=p, content=c) for p, c in files.items()])
    out = await commit_fix(ctx, fix)
    return out["pull_request"]["html_url"]


async def clone_token(user_id: str, owner: str, repo: str) -> str | None:
    """Web: a read-only token for this one repo if it is in the user's own installation, else None (public clone).
    Desktop: None, and the scan uses the user's own token from the keychain."""
    ctx = await resolve_repo(user_id, owner, repo)
    if ctx is None:
        return None
    try:
        return await gh.clone_token(ctx.installation_id, ctx.repo_id)
    except gh.GitHubError as e:
        log.warning("Clone token for %s failed: %s", ctx.full_name, e)
        return None


async def repo_info(user_id: str, owner: str, repo: str) -> dict | None:
    ctx = await resolve_repo(user_id, owner, repo)
    if ctx is None:
        return None
    return {"full_name": ctx.full_name, "private": ctx.private, "default_branch": ctx.default_branch,
            "description": None, "url": f"https://github.com/{ctx.full_name}"}


async def user_repos(user_id: str) -> list[dict]:
    if not app_enabled():
        return []
    out = []
    for inst in await _linked_installations(user_id):
        try:
            for r in await _installation_repos(inst["installation_id"]):
                out.append({"full_name": r["full_name"], "private": r["private"], "description": r.get("description"),
                            "url": f"https://github.com/{r['full_name']}"})
        except gh.GitHubError:
            continue
    return out


@router.get("/status")
async def status(user: dict = Depends(auth.current_claims)):
    """What the Integrations and Settings screens show. Web: the GitHub App; desktop: the keychain token."""
    if config.desktop_mode():
        from . import github
        return {"mode": "token", **await github.whoami()}
    if not app_enabled():
        return {"mode": "app", "configured": False, "ok": False, "installations": []}
    installs = await _linked_installations(user["sub"])
    return {"mode": "app", "configured": True, "ok": bool(installs),
            "installations": [{"installation_id": i["installation_id"], "account": i["github_account_login"],
                               "manage_url": _manage_url(i["installation_id"])} for i in installs]}
