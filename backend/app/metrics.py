"""In-process measurements: ingest latency/throughput and the last analysis stage timings."""
import statistics
import threading
from collections import deque

_lock = threading.Lock()
_ingest: deque = deque(maxlen=500)  # (events, ms)
_last_snapshot: dict = {}


def record_ingest(n: int, ms: float) -> None:
    with _lock:
        _ingest.append((n, ms))


def record_snapshot(timings: dict) -> None:
    global _last_snapshot
    with _lock:
        _last_snapshot = dict(timings)


def _pct(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int(round(p * (len(s) - 1))))]


def summary() -> dict:
    with _lock:
        rows = list(_ingest)
        snap = dict(_last_snapshot)
    per_event = [ms / n for n, ms in rows if n]
    tot_n, tot_ms = sum(n for n, _ in rows), sum(ms for _, ms in rows)
    return {
        "ingest_calls": len(rows),
        "events_ingested": tot_n,
        "ingest_ms_per_event_p50": round(_pct(per_event, 0.5), 4),
        "ingest_ms_per_event_p95": round(_pct(per_event, 0.95), 4),
        "ingest_events_per_sec": round(tot_n / (tot_ms / 1000), 1) if tot_ms else 0.0,
        "last_analysis_ms": snap,
    }
