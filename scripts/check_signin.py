#!/usr/bin/env python3
"""Check that GitHub sign-in can work, and say exactly what is missing. Prints no secret values.

Run from the repo root:   backend/.venv/bin/python scripts/check_signin.py
Reads backend/.env (or the process environment), then asks the Supabase project itself:
  - is the URL reachable and the anon key accepted?
  - is the GitHub provider enabled?
  - have the SQL migrations been applied?
"""
import os
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from app import config  # noqa: E402  (loads backend/.env)

OK, BAD, WARN = "  ok   ", "  FAIL ", "  warn "
problems = 0


def say(tag: str, msg: str) -> None:
    global problems
    problems += tag == BAD
    print(f"{tag}{msg}")


def main() -> int:
    env_file = ROOT / "backend" / ".env"
    print(f"backend/.env: {'found' if env_file.is_file() else 'MISSING (cp .env.example backend/.env)'}\n")
    url, anon = config.SUPABASE_URL, config.SUPABASE_ANON_KEY

    print("Required for sign-in")
    say(OK if url else BAD, "SUPABASE_URL is set" if url else "SUPABASE_URL is empty (Supabase > Project Settings > API > Project URL)")
    say(OK if anon else BAD, "SUPABASE_ANON_KEY is set" if anon else "SUPABASE_ANON_KEY is empty (Project Settings > API > publishable key)")
    if url and not re.fullmatch(r"https://[a-z0-9-]+\.supabase\.co", url):
        say(BAD, "SUPABASE_URL should look like https://<project-ref>.supabase.co (no path, no trailing slash)")
    if "your-project-ref" in url or "your-publishable" in anon:
        say(BAD, "SUPABASE_URL / SUPABASE_ANON_KEY still hold the .env.example placeholders")
    if anon.startswith("sb_secret") or anon.count(".") == 2 and '"role":"service_role"' in anon:
        say(BAD, "SUPABASE_ANON_KEY looks like a service/secret key; use the publishable (anon) key")
    if not (url and anon):
        print("\nSet the two values above, then run this again.")
        return 1

    print("\nSupabase project")
    headers = {"apikey": anon}
    try:
        r = httpx.get(f"{url}/auth/v1/settings", headers=headers, timeout=10)
    except httpx.HTTPError as e:
        say(BAD, f"cannot reach {url}: {type(e).__name__}. Check the URL and your internet connection.")
        return 1
    if r.status_code in (401, 403):
        say(BAD, "the project rejected SUPABASE_ANON_KEY (wrong project, or a rotated key)")
        return 1
    if r.status_code != 200:
        say(BAD, f"unexpected answer from the auth service: HTTP {r.status_code}")
        return 1
    s = r.json()
    say(OK, "project reachable, anon key accepted")
    github = (s.get("external") or {}).get("github")
    say(OK if github else BAD, "GitHub provider is enabled" if github else
        "GitHub provider is DISABLED: Supabase > Authentication > Sign In / Providers > GitHub, add the OAuth app's "
        "Client ID and secret")
    if s.get("disable_signup"):
        say(WARN, "new sign-ups are disabled in this project; only existing users can sign in")

    print("\nData layer (migrations)")
    for table in ("profiles", "jobs", "events", "prefs"):
        t = httpx.get(f"{url}/rest/v1/{table}?select=*&limit=0", headers=headers, timeout=10)
        if t.status_code in (200, 206):
            say(OK, f"table '{table}' exists")
        elif t.status_code == 404 or "PGRST205" in t.text or "does not exist" in t.text:
            say(BAD, f"table '{table}' missing: run supabase/migrations/0001..0003 in the SQL editor, in order")
        else:
            say(WARN, f"table '{table}': HTTP {t.status_code} (RLS may be hiding it from an anonymous caller; fine)")

    print("\nRedirect URLs (Supabase > Authentication > URL Configuration). I cannot read these; confirm by eye:")
    for u in (f"{config.app_url()}/api/auth/callback", "http://127.0.0.1:*/api/auth/callback  (desktop app)"):
        print(f"  - {u}")
    print(f"GitHub OAuth app callback must be exactly:  {url}/auth/v1/callback")

    print("\nOptional")
    say(OK if config.SUPABASE_SERVICE_KEY else WARN,
        "SUPABASE_SERVICE_KEY is set (web server only)" if config.SUPABASE_SERVICE_KEY
        else "SUPABASE_SERVICE_KEY empty: fine for the desktop app; the web server needs it for repo access")
    say(OK if config.GITHUB_ENABLED else WARN,
        "GitHub App is fully configured (repo access)" if config.GITHUB_ENABLED
        else "GitHub App not configured: sign-in works, private-repo access is off")
    print("\n" + ("Sign-in should work." if not problems else f"{problems} problem(s) to fix before sign-in works."))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
