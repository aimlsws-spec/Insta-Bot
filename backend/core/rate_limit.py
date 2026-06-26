"""
core/rate_limit.py
In-memory sliding-window rate limiter for FastAPI.
No Redis, no external dependencies — safe for single-process deployment.
"""

import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# (max_requests, window_seconds)
_RULES: list[Tuple[str, int, int]] = [
    ("/api/auth/login",           10,  15 * 60),
    ("/api/auth/register",        10,  15 * 60),
    ("/api/webhook/instagram",   120,       60),
]
_DEFAULT_API_LIMIT = (300, 60)

# ip -> path_prefix -> deque of timestamps
_store: Dict[str, Dict[str, Deque[float]]] = defaultdict(lambda: defaultdict(deque))


def _get_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_limited(ip: str, key: str, max_requests: int, window: int) -> bool:
    now   = time.monotonic()
    cutoff = now - window
    q     = _store[ip][key]

    # evict expired timestamps
    while q and q[0] < cutoff:
        q.popleft()

    if len(q) >= max_requests:
        return True

    q.append(now)
    return False


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        ip   = _get_ip(request)

        for prefix, max_req, window in _RULES:
            if path == prefix or path.startswith(prefix + "/"):
                if _is_limited(ip, prefix, max_req, window):
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Rate limit exceeded"},
                    )
                return await call_next(request)

        if path.startswith("/api/"):
            if _is_limited(ip, "__api__", *_DEFAULT_API_LIMIT):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded"},
                )

        return await call_next(request)
