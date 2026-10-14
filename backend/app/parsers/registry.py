from ..models import Event
from . import linux_auth, snort_alert, web_access

PARSERS = {"linux_auth": linux_auth.parse, "web_access": web_access.parse, "snort_alert": snort_alert.parse}


def parse_lines(fmt: str, lines: list[str]) -> tuple[list[Event], list[dict]]:
    if fmt not in PARSERS:
        raise KeyError(fmt)
    ok, bad = [], []
    for i, ln in enumerate(lines):
        if not ln.strip():
            continue
        try:
            ok.append(PARSERS[fmt](ln))
        except (ValueError, KeyError) as e:
            bad.append({"line": i, "error": str(e)[:120]})
    return ok, bad
