"""Server settings from the environment (and backend/.env in development).

Two deployments share this code:
- web: the hosted server. Has the Supabase service key and the GitHub App credentials.
- desktop (DESKTOP_MODE=1): the engine bundled in the Electron app, on the user's own machine. It must never hold
  a server secret, so the service key and GitHub App settings are ignored there even if present.
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # optional: env vars can come from the process (Docker, Electron)
    load_dotenv = None

BACKEND_DIR = Path(__file__).resolve().parent.parent
if load_dotenv and os.environ.get("APC_SKIP_DOTENV") != "1":
    load_dotenv(BACKEND_DIR / ".env")


def desktop_mode() -> bool:
    return os.environ.get("DESKTOP_MODE") == "1"


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _github_private_key() -> str:
    """PEM from GITHUB_APP_PRIVATE_KEY_PATH (relative to backend/) or inline GITHUB_APP_PRIVATE_KEY."""
    if path := _env("GITHUB_APP_PRIVATE_KEY_PATH"):
        p = Path(path)
        if not p.is_absolute():
            p = BACKEND_DIR / p
        return p.read_text() if p.is_file() else ""
    # Inline form: env files usually hold the PEM on one line with literal \n
    return _env("GITHUB_APP_PRIVATE_KEY").replace("\\n", "\n")


SUPABASE_URL = _env("SUPABASE_URL").rstrip("/")
SUPABASE_ANON_KEY = _env("SUPABASE_ANON_KEY")
# Server only. Bypasses row-level security: used for the few things a user must not be able to do themselves
# (reading their GitHub identity, single-use install states, the GitHub App audit log).
SUPABASE_SERVICE_KEY = "" if desktop_mode() else _env("SUPABASE_SERVICE_KEY")
# Only for legacy projects that sign JWTs with HS256; empty means verify with the project's JWKS.
SUPABASE_JWT_SECRET = _env("SUPABASE_JWT_SECRET")
SUPABASE_ENABLED = bool(SUPABASE_URL and SUPABASE_ANON_KEY)

# GitHub App for repo access (web only). Without it, sign-in still works and /api/github/* returns 503.
_web = not desktop_mode()
GITHUB_APP_ID = _env("GITHUB_APP_ID") if _web else ""
GITHUB_APP_SLUG = _env("GITHUB_APP_SLUG") if _web else ""
GITHUB_APP_CLIENT_ID = _env("GITHUB_APP_CLIENT_ID") if _web else ""
GITHUB_APP_CLIENT_SECRET = _env("GITHUB_APP_CLIENT_SECRET") if _web else ""
GITHUB_APP_PRIVATE_KEY = _github_private_key() if _web else ""
# Accounts the app must never be linked to (e.g. the official hackathon org), comma-separated
GITHUB_BLOCKED_ACCOUNTS = {a.strip().lower() for a in _env("GITHUB_BLOCKED_ACCOUNTS").split(",") if a.strip()}
GITHUB_ENABLED = all((GITHUB_APP_ID, GITHUB_APP_SLUG, GITHUB_APP_CLIENT_ID, GITHUB_APP_CLIENT_SECRET,
                      GITHUB_APP_PRIVATE_KEY, SUPABASE_SERVICE_KEY))


# Vercel (and similar) run requests as short-lived functions: no background threads that outlive a response, no git
# binary, no persistent disk. Repository scans are therefore unavailable there; everything else works.
SERVERLESS = bool(os.environ.get("VERCEL"))
SERVERLESS_SCAN_MESSAGE = ("Repository scans are not available on this hosted site, because it runs as short-lived "
                           "functions. Use the Paladin desktop app (or a server that stays running) to scan a repository.")


def app_url() -> str:
    """The origin the browser uses. Web: APP_URL. Desktop: the engine's own loopback address."""
    if desktop_mode():
        return f"http://127.0.0.1:{os.environ.get('PORT', '8000')}"
    if _env("APP_URL"):
        return _env("APP_URL").rstrip("/")
    # hosting platforms that give every service an https address: no domain of your own is needed
    if _env("VERCEL_PROJECT_PRODUCTION_URL"):   # the stable production alias (VERCEL_URL changes every deployment)
        return f"https://{_env('VERCEL_PROJECT_PRODUCTION_URL')}"
    if _env("RENDER_EXTERNAL_URL"):
        return _env("RENDER_EXTERNAL_URL").rstrip("/")
    if _env("FLY_APP_NAME"):
        return f"https://{_env('FLY_APP_NAME')}.fly.dev"
    if _env("RAILWAY_PUBLIC_DOMAIN"):
        return f"https://{_env('RAILWAY_PUBLIC_DOMAIN')}"
    return "http://localhost:5173"


def secure_cookies() -> bool:
    return os.environ.get("COOKIE_SECURE", "1") == "1"
