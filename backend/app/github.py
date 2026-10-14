"""Minimal GitHub REST client for repository onboarding: parse links, resolve a repo, list the user's repos."""
import hashlib
import os
import re
import time

import httpx

from . import keys

TRANSPORT = None  # tests inject an httpx transport
API = "https://api.github.com"
_NAME = r"[A-Za-z0-9_.-]{1,100}"
_OWNER = r"[A-Za-z0-9-]{1,39}"          # GitHub account names have no dots or underscores
_FILE_EXT = {"py", "js", "ts", "tsx", "jsx", "md", "json", "txt", "yml", "yaml", "toml", "html", "css", "go", "rs", "java", "c", "h", "sh", "ini", "cfg", "lock", "xml", "csv"}
_HTTPS = re.compile(rf"^https://(?:www\.)?github\.com/({_OWNER})/({_NAME}?)(?:\.git)?(?:/(?:tree|blob|pull|issues|commit|releases)/.*)?/?$")
_SSH = re.compile(rf"^git@github\.com:({_OWNER})/({_NAME}?)(?:\.git)?$")
_BARE = re.compile(rf"^(?:github\.com/)?({_OWNER})/({_NAME}?)(?:\.git)?/?$")
_cache: dict[str, tuple[float, list]] = {}


class GitHubError(Exception):
    def __init__(self, kind: str, message: str, status: int | None = None):
        super().__init__(message)
        self.kind, self.message, self.status = kind, message, status


def parse(text: str) -> tuple[str, str] | None:
    """(owner, repo) from a link, ssh remote, or owner/name; None for anything else (including path tricks)."""
    t = (text or "").strip()
    if not t or len(t) > 300:
        return None
    for rx in (_HTTPS, _SSH, _BARE):
        m = rx.match(t)
        if m:
            owner, repo = m.group(1), m.group(2)
            if any(set(x) <= {"."} for x in (owner, repo)):   # "." and ".." are not names
                return None
            if rx is _BARE and repo.rsplit(".", 1)[-1].lower() in _FILE_EXT and "." in repo:
                return None                                  # "src/main.py" is a path, not a repository
            return owner, repo
    return None


def canonical(owner: str, repo: str) -> str:
    return f"https://github.com/{owner}/{repo}"


def clear_cache() -> None:
    _cache.clear()


def _classify(r: httpx.Response) -> GitHubError:
    try:
        msg = (r.json() or {}).get("message", "")
    except ValueError:
        msg = ""
    if r.status_code == 401:
        return GitHubError("auth", "GitHub rejected the token. Check it in Settings.", 401)
    if r.status_code in (403, 429) and (r.headers.get("x-ratelimit-remaining") == "0" or "rate limit" in msg.lower()):
        return GitHubError("rate_limit", "GitHub rate limit reached. Add a token in Settings or try again later.", 429)
    if r.status_code in (403, 404):
        hint = ("add a GitHub token in Settings" if os.environ.get("DESKTOP_MODE") == "1"
                else "connect it through the GitHub App on the Integrations page")
        return GitHubError("not_found", f"Repository not found. If it is private, {hint}.", 404)
    if r.status_code >= 500:
        return GitHubError("server", "GitHub is having problems. Try again shortly.", r.status_code)
    return GitHubError("invalid", msg or f"GitHub returned HTTP {r.status_code}.", r.status_code)


async def _get(path: str, params: dict | None = None, token: str | None = None):
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "paladin"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(base_url=API, transport=TRANSPORT, timeout=httpx.Timeout(15.0)) as c:
            return await c.get(path, params=params, headers=headers)
    except httpx.HTTPError as e:
        raise GitHubError("network", "Could not reach GitHub. Check your internet connection.") from e


async def repo(owner: str, name: str) -> dict:
    r = await _get(f"/repos/{owner}/{name}", token=keys.get("GITHUB_TOKEN"))
    if r.status_code != 200:
        raise _classify(r)
    d = r.json()
    return {"full_name": d.get("full_name") or f"{owner}/{name}", "private": bool(d.get("private")),
            "default_branch": d.get("default_branch") or "main", "description": d.get("description"),
            "url": d.get("html_url") or canonical(owner, name)}


async def user_repos() -> list[dict]:
    token = keys.get("GITHUB_TOKEN")
    if not token:
        return []
    ck = hashlib.sha256(token.encode()).hexdigest()
    hit = _cache.get(ck)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    r = await _get("/user/repos", {"per_page": 100, "sort": "pushed", "affiliation": "owner,collaborator,organization_member"}, token)
    if r.status_code != 200:
        raise _classify(r)
    out = [{"full_name": d["full_name"], "private": bool(d.get("private")), "description": d.get("description"),
            "url": d.get("html_url") or f"https://github.com/{d['full_name']}"} for d in r.json() if d.get("full_name")]
    _cache[ck] = (time.time(), out)
    return out


async def whoami() -> dict:
    token = keys.get("GITHUB_TOKEN")
    if not token:
        return {"configured": False, "ok": False}
    try:
        r = await _get("/user", token=token)
    except GitHubError as e:
        return {"configured": True, "ok": False, "error": e.message}
    if r.status_code != 200:
        e = _classify(r)
        return {"configured": True, "ok": False, "error": e.message if e.kind != "not_found" else "GitHub rejected the token."}
    scopes = [s.strip() for s in r.headers.get("x-oauth-scopes", "").split(",") if s.strip()]
    return {"configured": True, "ok": True, "login": r.json().get("login"), "scopes": scopes}
