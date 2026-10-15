"""Per-user preferences with a closed schema: unknown keys and bad values are rejected, and a bad patch applies
nothing. Defaults are the single source of truth; the UI renders whatever this returns."""
from . import supa

DEFAULTS: dict = {
    "general.startup": "home",            # home | last
    "general.after_import": "repository", # repository | analysis
    "general.onboarding_dismissed": False,
    "general.setup_done": False,          # a provider, key and model were validated by a real round trip
    "general.setup_skipped": False,       # the user chose to set up later; the guided flow stops opening itself
    "workspaces.sort": "recent",          # recent | name | events
    "appearance.density": "comfortable",  # comfortable | compact
    "appearance.graph_labels": True,
    "diff.wrap": True,
    "diff.font_size": 12,
    "assistant.provider": "",
    "assistant.model": "",
    "assistant.effort": "",
    "assistant.context": True,
}
_ENUM = {
    "general.startup": {"home", "last"}, "general.after_import": {"repository", "analysis"},
    "workspaces.sort": {"recent", "name", "events"},
    "appearance.density": {"comfortable", "compact"}, "assistant.provider": {"", "anthropic", "openai"},
    "assistant.effort": {"", "low", "medium", "high"},
}
_INT = {"diff.font_size": (10, 16)}
_STR = {"assistant.model": 128}


def _check(key: str, value) -> None:
    if key not in DEFAULTS:
        raise ValueError(f"unknown setting: {key}")
    default = DEFAULTS[key]
    if key in _ENUM:
        if not isinstance(value, str) or value not in _ENUM[key]:   # lists/dicts are unhashable
            raise ValueError(f"{key} must be one of {sorted(_ENUM[key])}")
    elif key in _INT:
        lo, hi = _INT[key]
        if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
            raise ValueError(f"{key} must be a whole number from {lo} to {hi}")
    elif key in _STR:
        if not isinstance(value, str) or len(value) > _STR[key]:
            raise ValueError(f"{key} must be text up to {_STR[key]} characters")
    elif isinstance(default, bool):
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")


def get(user_id: str) -> dict:
    out = dict(DEFAULTS)
    for r in supa.select("prefs", {"user_id": supa.eq(user_id)}, columns="key,value"):
        if r["key"] in DEFAULTS:
            try:
                v = r["value"]
                _check(r["key"], v)
                out[r["key"]] = v
            except (ValueError, TypeError):
                pass          # a stored value that no longer validates falls back to the default
    return out


def patch(user_id: str, changes: dict) -> dict:
    for k, v in changes.items():
        _check(k, v)
    if changes:   # one request, so a bad patch applies nothing
        supa.upsert("prefs", [{"user_id": user_id, "key": k, "value": v} for k, v in changes.items()], "user_id,key")
    return get(user_id)
