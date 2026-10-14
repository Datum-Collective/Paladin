import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class RateLimit:
    """In-memory sliding-window limiter. Fine for a single instance.

    Used as a dependency it keys by client IP; call `hit(key)` to key by something else (e.g. user id).
    """

    def __init__(self, limit: int, window_s: int):
        self.limit = limit
        self.window_s = window_s
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str):
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > self.window_s:
            q.popleft()
        if len(q) >= self.limit:
            raise HTTPException(429, "Too many requests")
        q.append(now)

    def __call__(self, request: Request):
        # Caddy replaces X-Forwarded-For with the real client and uvicorn (--proxy-headers) applies it,
        # so request.client is the caller; a spoofed header from the client never reaches us as-is
        self.hit(request.client.host if request.client else "?")
