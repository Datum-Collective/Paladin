import threading
import time
from collections import deque

from fastapi import HTTPException, Request


class RateLimit:
    """In-memory sliding-window limiter. Fine for a single instance.

    Used as a dependency it keys by client IP; call `hit(key)` to key by something else (e.g. user id).
    Thread-safe (sync endpoints run in a thread pool) and bounded: keys that have gone quiet are dropped, so an
    attacker rotating source addresses cannot grow it without limit.
    """

    SWEEP_EVERY_S = 30

    def __init__(self, limit: int, window_s: int):
        self.limit = limit
        self.window_s = window_s
        self.hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._swept = time.monotonic()

    def _sweep(self, now: float) -> None:
        self._swept = now
        for k in [k for k, q in self.hits.items() if not q or now - q[-1] > self.window_s]:
            del self.hits[k]

    def hit(self, key: str):
        now = time.monotonic()
        with self._lock:
            if now - self._swept > self.SWEEP_EVERY_S:
                self._sweep(now)
            q = self.hits.get(key)
            if q is None:
                q = self.hits[key] = deque()
            while q and now - q[0] > self.window_s:
                q.popleft()
            if len(q) >= self.limit:
                raise HTTPException(429, "Too many requests")
            q.append(now)

    def __call__(self, request: Request):
        # Caddy replaces X-Forwarded-For with the real client and uvicorn (--proxy-headers) applies it,
        # so request.client is the caller; a spoofed header from the client never reaches us as-is
        self.hit(request.client.host if request.client else "?")
