#!/usr/bin/env python3
"""Check that GitHub sign-in can work, and say exactly what is missing. Prints no secret values.

Run from the repo root:   backend/.venv/bin/python scripts/check_signin.py
Production preflight:     backend/.venv/bin/python scripts/check_signin.py --production --env .env
Reads backend/.env (or --env FILE, or the process environment), then asks the Supabase project itself:
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
ARGS = sys.argv[1:]
PRODUCTION = "--production" in ARGS
ENV_FILE = Path(ARGS[ARGS.index("--env") + 1]) if "--env" in ARGS else None


def _load_env_file(path: Path) -> None:
    """Minimal KEY=VALUE reader for the docker-compose .env (no export, no interpolation)."""
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip().strip("'\"")


if ENV_FILE:
    if not ENV_FILE.is_file():
        sys.exit(f"--env file not found: {ENV_FILE}")
    os.environ["APC_SKIP_DOTENV"] = "1"       # do not mix in backend/.env
    _load_env_file(ENV_FILE)
sys.path.insert(0, str(ROOT / "backend"))
from app import config  # noqa: E402  (loads backend/.env unless --env was given)

OK, BAD, WARN = "  ok   ", "  FAIL ", "  warn "
problems = 0


def say(tag: str, msg: str) -> None:
    global problems
    problems += tag == BAD
    print(f"{tag}{msg}")


def production_checks(supabase_url: str) -> None:
    from urllib.parse import urlparse
    print("\nProduction settings")
    app = config.app_url()
    u = urlparse(app)
    host = u.hostname or ""
    local = host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local") or host.endswith(".invalid")
    say(OK if u.scheme == "https" else BAD, f"APP_URL is https ({app})" if u.scheme == "https"
        else f"APP_URL must be https in production (is {app or 'empty'})")
    say(BAD if local else OK, "APP_URL is a real public host" if not local else
        f"APP_URL host '{host}' is not a public domain")
    domain = os.environ.get("APP_DOMAIN", "").strip()
    say(OK if domain and domain == host else BAD, f"APP_DOMAIN matches APP_URL ({domain})" if domain and domain == host
        else f"APP_DOMAIN ('{domain}') must equal the APP_URL host ('{host}'); Caddy issues the certificate for it")
    say(OK if config.secure_cookies() else BAD, "COOKIE_SECURE is on" if config.secure_cookies()
        else "COOKIE_SECURE=0 in production sends the session cookie over plain http")
    say(OK if config.SUPABASE_SERVICE_KEY else BAD, "SUPABASE_SERVICE_KEY is set (the web server needs it)"
        if config.SUPABASE_SERVICE_KEY else "SUPABASE_SERVICE_KEY is empty: web sign-in cannot link GitHub identities")
    say(OK if not os.environ.get("ALLOWED_ORIGINS") else BAD, "ALLOWED_ORIGINS is empty (no cross-origin access)"
        if not os.environ.get("ALLOWED_ORIGINS") else "ALLOWED_ORIGINS must be empty in production")
    say(OK if os.environ.get("DESKTOP_MODE") != "1" else BAD, "DESKTOP_MODE is off"
        if os.environ.get("DESKTOP_MODE") != "1" else "DESKTOP_MODE=1 turns on the local-account endpoints; never on a server")
    if not local and u.scheme == "https":
        print(f"\nAdd to Supabase > Authentication > URL Configuration:\n  Site URL:      {app}\n"
              f"  Redirect URL:  {app}/api/auth/callback")
        try:
            r = httpx.get(f"{app}/health", timeout=10, follow_redirects=True)
            ok = r.status_code == 200
            say(OK if ok else WARN, f"{app}/health answers" if ok else f"{app}/health returned HTTP {r.status_code}")
            if ok:
                c = httpx.get(f"{app}/api/config", timeout=10).json()
                say(OK if c.get("signin") else BAD, "deployed server reports sign-in configured" if c.get("signin")
                    else f"deployed server says sign-in is NOT configured (missing: {c.get('signin_missing')})")
        except httpx.HTTPError as e:
            say(WARN, f"{app} not reachable yet ({type(e).__name__}); fine before the first deploy, "
                      "check DNS and ports 80/443 after")


def main() -> int:
    env_file = ENV_FILE or ROOT / "backend" / ".env"
    print(f"{env_file}: {'found' if env_file.is_file() else 'MISSING (cp .env.example backend/.env)'}\n")
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

    if PRODUCTION:
        production_checks(url)
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
