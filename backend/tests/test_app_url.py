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
