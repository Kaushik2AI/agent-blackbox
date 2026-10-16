"""Small fixed-window rate limits in Redis for the public demo (real-model calls cost
money). Counters: per client IP per hour, and a global daily cap for real-model runs."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Request
from redis import Redis


class RateLimited(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def client_ip(request: Request) -> str:
    # Behind the Next.js server (and the host's proxy) the browser's address arrives in
    # X-Forwarded-For; the left-most entry is the original client.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unknown"


def _hit(redis: Redis, key: str, limit: int, ttl_s: int) -> bool:
    count = int(redis.incr(key))
    if count == 1:
        redis.expire(key, ttl_s)  # Redis 6.2 has no EXPIRE NX; first hit sets the window
    return count <= limit


def check(redis: Redis, ip: str, *, per_ip_per_hour: int, llm: bool, llm_per_day: int) -> None:
    now = datetime.now(UTC)
    hour = now.strftime("%Y%m%d%H")
    if not _hit(redis, f"rl:ip:{ip}:{hour}:{'llm' if llm else 'any'}", per_ip_per_hour, 3700):
        raise RateLimited(
            f"Too many runs from your address this hour (limit {per_ip_per_hour}). "
            "Try again later, or use the scripted agent."
        )
    if llm and not _hit(redis, f"rl:llm:{now:%Y%m%d}", llm_per_day, 90000):
        raise RateLimited(
            "The live AI has reached today's usage cap for this demo. "
            "The scripted agent still works."
        )
