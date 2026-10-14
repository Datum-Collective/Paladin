"""PostgREST and the Supabase admin API with the SERVICE key (web server only).

The service key BYPASSES row-level security: every query here must filter by user_id explicitly. It is used only
where the user must not be able to act on their own: reading the GitHub identity they signed in with, single-use
GitHub App install states, linking installations, and the GitHub App audit log. Everything else goes through
supa.py as the user.
"""
from . import config
from .http import client


class NoServiceKey(RuntimeError):
    pass


def _headers() -> dict:
    if not config.SUPABASE_SERVICE_KEY or config.desktop_mode():
        raise NoServiceKey("the service key is only available on the web server")
    return {"apikey": config.SUPABASE_SERVICE_KEY, "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}"}


def _rest(table: str) -> str:
    return f"{config.SUPABASE_URL}/rest/v1/{table}"


async def select(table: str, params: dict) -> list[dict]:
    r = await client.get(_rest(table), headers=_headers(), params=params)
    r.raise_for_status()
    return r.json()


async def insert(table: str, row: dict) -> dict:
    r = await client.post(_rest(table), headers={**_headers(), "Prefer": "return=representation"}, json=row)
    r.raise_for_status()
    return r.json()[0]


async def insert_ignore_duplicate(table: str, row: dict, on_conflict: str):
    """Insert; a row with the same `on_conflict` key already existing is not an error.
    Other constraint violations still raise."""
    r = await client.post(_rest(table), headers={**_headers(), "Prefer": "resolution=ignore-duplicates,return=minimal"},
                          params={"on_conflict": on_conflict}, json=row)
    r.raise_for_status()


async def delete(table: str, params: dict) -> list[dict]:
    """Delete matching rows and return them. A single statement, so safe for single-use tokens:
    of two concurrent deletes of the same row, only one gets it back."""
    r = await client.delete(_rest(table), headers={**_headers(), "Prefer": "return=representation"}, params=params)
    r.raise_for_status()
    return r.json()


async def github_user_id(user_id: str) -> int | None:
    """The GitHub account ID this Supabase user signed in with.

    Read from auth.identities via the admin API, NOT from the JWT's user_metadata:
    users can rewrite their own user_metadata through Supabase's public API.
    """
    r = await client.get(f"{config.SUPABASE_URL}/auth/v1/admin/users/{user_id}", headers=_headers())
    r.raise_for_status()
    for identity in r.json().get("identities") or []:
        if identity.get("provider") == "github" and str(identity.get("id", "")).isdigit():
            return int(identity["id"])
    return None
