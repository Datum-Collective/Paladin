"""Vercel entry point: exposes the FastAPI app as one serverless function behind /api/* and /health.

The static UI is served by Vercel's CDN from frontend/dist, so STATIC_DIR is deliberately not set here."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("SEED_DIR", str(ROOT / "data"))      # inventory, ATT&CK subset, sample logs
os.environ.setdefault("DATA_DIR", "/tmp/apc")              # the only writable path on Vercel
os.environ.setdefault("APC_SKIP_DOTENV", "1")              # configuration comes from Vercel project env vars

from app.main import app  # noqa: E402,F401  (Vercel looks for a module-level ASGI `app`)
