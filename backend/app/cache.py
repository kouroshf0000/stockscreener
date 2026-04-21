from redis.asyncio import Redis, from_url

from backend.app.config import get_settings

_redis: Redis | None = None


def get_redis() -> Redis | None:
    global _redis
    url = get_settings().redis_url
    if not url or not url.startswith(("redis://", "rediss://", "unix://")):
        return None
    if _redis is None:
        _redis = from_url(url, decode_responses=True)
    return _redis
