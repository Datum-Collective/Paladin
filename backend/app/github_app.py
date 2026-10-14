"""GitHub App authentication and raw GitHub API calls.

Tokens and the private key live only in this module's memory. The one token that leaves it is
`clone_token`: a read-only token for a single repo, handed straight to git (as an HTTP header in
git's environment) for a scan. Nothing here logs a token: errors carry only the HTTP status and
GitHub's `message` field.
"""
import time
from datetime import datetime

import httpx
import jwt

from . import config
from .http import client

API = "https://api.github.com"
_API_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
# Re-mint installation tokens this long before GitHub expires them (they last 1 hour)
_TOKEN_REFRESH_MARGIN_S = 300

# (installation_id, repo_id or None, permissions) -> (token, expires_at epoch seconds)
_installation_tokens: dict[tuple, tuple[str, float]] = {}
READ_CONTENTS = (("contents", "read"),)


class GitHubError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"GitHub {status}: {message}")
        self.status = status


def _message(r: httpx.Response) -> str:
    try:
        return str(r.json().get("message", ""))[:200]
    except ValueError:
        return ""


def _app_jwt() -> str:
    now = int(time.time())
    # iat backdated for clock drift; GitHub caps exp at 10 minutes
    return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": config.GITHUB_APP_CLIENT_ID},
                      config.GITHUB_APP_PRIVATE_KEY, algorithm="RS256")


async def _installation_token(installation_id: int, repo_id: int | None, permissions: tuple = ()) -> str:
    key = (installation_id, repo_id, permissions)
    cached = _installation_tokens.get(key)
    if cached and cached[1] - time.time() > _TOKEN_REFRESH_MARGIN_S:
        return cached[0]
    # A repo-scoped token can't touch any other repo, even if a bug upstream picked the wrong one
    body: dict = {"repository_ids": [repo_id]} if repo_id is not None else {}
    if permissions:
        body["permissions"] = dict(permissions)
    r = await client.post(f"{API}/app/installations/{installation_id}/access_tokens",
                          headers={**_API_HEADERS, "Authorization": f"Bearer {_app_jwt()}"}, json=body)
    if r.status_code != 201:
        raise GitHubError(r.status_code, f"installation token: {_message(r)}")
    data = r.json()
    expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")).timestamp()
    _installation_tokens[key] = (data["token"], expires)
    return data["token"]


async def clone_token(installation_id: int, repo_id: int) -> str:
    """Read-only (contents: read) token for exactly one repo, for `git clone` in a scan. Expires within an hour."""
    return await _installation_token(installation_id, repo_id, READ_CONTENTS)


def forget_installation(installation_id: int):
    for key in [k for k in _installation_tokens if k[0] == installation_id]:
        del _installation_tokens[key]


async def as_installation(method: str, path: str, *, installation_id: int, repo_id: int | None = None,
                          params: dict | None = None, json: dict | None = None) -> httpx.Response:
    """Call the GitHub API as the installation. `path` must be built server-side, never taken from input."""
    for attempt in (1, 2):
        token = await _installation_token(installation_id, repo_id)
        r = await client.request(method, f"{API}{path}", params=params, json=json,
                                 headers={**_API_HEADERS, "Authorization": f"Bearer {token}"})
        if r.status_code == 401 and attempt == 1:
            # Token revoked early (e.g. app reinstalled): mint a fresh one once
            _installation_tokens.pop((installation_id, repo_id, ()), None)
            continue
        return r
    return r


async def paginate_installation(path: str, key: str, *, installation_id: int, max_pages: int = 10) -> list[dict]:
    items: list[dict] = []
    for page in range(1, max_pages + 1):
        r = await as_installation("GET", path, installation_id=installation_id,
                                  params={"per_page": 100, "page": page})
        if r.status_code != 200:
            raise GitHubError(r.status_code, f"{path}: {_message(r)}")
        batch = r.json()[key]
        items.extend(batch)
        if len(batch) < 100:
            break
    return items


# --- User-to-server token: used only inside the install callback, then revoked ---

async def exchange_code(code: str) -> str:
    r = await client.post("https://github.com/login/oauth/access_token",
                          headers={"Accept": "application/json"},
                          data={"client_id": config.GITHUB_APP_CLIENT_ID,
                                "client_secret": config.GITHUB_APP_CLIENT_SECRET,
                                "code": code})
    data = r.json() if r.status_code == 200 else {}
    if "access_token" not in data:
        # GitHub reports bad codes as 200 + {"error": ...}
        raise GitHubError(r.status_code, f"code exchange: {data.get('error', '')} {data.get('error_description', '')}")
    return data["access_token"]


async def as_user(user_token: str, path: str, params: dict | None = None) -> httpx.Response:
    return await client.get(f"{API}{path}", params=params,
                            headers={**_API_HEADERS, "Authorization": f"Bearer {user_token}"})


async def user_installations(user_token: str) -> list[dict]:
    items: list[dict] = []
    for page in range(1, 11):
        r = await as_user(user_token, "/user/installations", {"per_page": 100, "page": page})
        if r.status_code != 200:
            raise GitHubError(r.status_code, f"/user/installations: {_message(r)}")
        batch = r.json()["installations"]
        items.extend(batch)
        if len(batch) < 100:
            break
    return items


async def revoke_user_token(user_token: str):
    """Best effort: we never store the token, and revoking it means a leak elsewhere is useless too."""
    try:
        await client.request("DELETE", f"{API}/applications/{config.GITHUB_APP_CLIENT_ID}/token",
                             auth=(config.GITHUB_APP_CLIENT_ID, config.GITHUB_APP_CLIENT_SECRET),
                             headers=_API_HEADERS, json={"access_token": user_token})
    except httpx.HTTPError:
        pass
