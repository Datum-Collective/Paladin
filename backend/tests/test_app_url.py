"""app_url(): explicit APP_URL wins; hosting platforms supply an https address so no domain is required."""
import pytest

from app import config

PLATFORM = ("APP_URL", "RENDER_EXTERNAL_URL", "FLY_APP_NAME", "RAILWAY_PUBLIC_DOMAIN", "DESKTOP_MODE")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in PLATFORM:
        monkeypatch.delenv(k, raising=False)


def test_default_is_the_vite_dev_origin():
    assert config.app_url() == "http://localhost:5173"


def test_explicit_app_url_wins_and_loses_its_slash(monkeypatch):
    monkeypatch.setenv("APP_URL", "https://paladin.example.com/")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://other.onrender.com")
    assert config.app_url() == "https://paladin.example.com"


def test_render_fly_and_railway_addresses(monkeypatch):
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://paladin.onrender.com")
    assert config.app_url() == "https://paladin.onrender.com"
    monkeypatch.delenv("RENDER_EXTERNAL_URL")
    monkeypatch.setenv("FLY_APP_NAME", "paladin-datum")
    assert config.app_url() == "https://paladin-datum.fly.dev"
    monkeypatch.delenv("FLY_APP_NAME")
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "paladin.up.railway.app")
    assert config.app_url() == "https://paladin.up.railway.app"


def test_desktop_ignores_all_of_it(monkeypatch):
    monkeypatch.setenv("DESKTOP_MODE", "1")
    monkeypatch.setenv("APP_URL", "https://paladin.example.com")
    monkeypatch.setenv("PORT", "4321")
    assert config.app_url() == "http://127.0.0.1:4321"


def test_vercel_uses_the_stable_production_alias_not_the_per_deployment_url(monkeypatch):
    monkeypatch.setenv("VERCEL_URL", "paladin-abc123-team.vercel.app")            # changes every deployment
    monkeypatch.setenv("VERCEL_PROJECT_PRODUCTION_URL", "paladin-datum.vercel.app")
    assert config.app_url() == "https://paladin-datum.vercel.app"


def test_serverless_blocks_scans_with_a_clear_message_and_says_so_in_config(client, monkeypatch):
    from app import harness
    from app import config as settings
    monkeypatch.setattr(settings, "SERVERLESS", True)
    with pytest.raises(RuntimeError, match="not available on this hosted site"):
        harness.start(1, "https://github.com/a/b")
    assert client.get("/api/config").json()["scans"] is False
    monkeypatch.setattr(settings, "SERVERLESS", False)
    assert client.get("/api/config").json()["scans"] is True


def test_vercel_entrypoint_exposes_the_asgi_app():
    """api/index.py is what Vercel runs: it must import cleanly and expose the same routes as the server."""
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    code = ("import api.index as m; paths={r.path for r in m.app.routes}; "
            "assert '/health' in paths and '/api/config' in paths and '/api/auth/login' in paths, paths; print('ok')")
    r = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True,
                       env={"PATH": __import__("os").environ["PATH"], "PYTHONPATH": str(root), "APC_SKIP_DOTENV": "1",
                            # Windows cannot start Python's networking (asyncio) without SYSTEMROOT
                            **{k: v for k, v in __import__("os").environ.items() if k.upper() == "SYSTEMROOT"}})
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr[-400:]
