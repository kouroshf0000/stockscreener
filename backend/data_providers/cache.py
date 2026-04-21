from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import BaseModel

from backend.app.cache import get_redis

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)


def key(*parts: str) -> str:
    return ":".join(["alpha", *parts])


async def cached(
    redis_key: str,
    ttl_s: int,
    model: type[T],
    loader: Callable[[], Awaitable[T]],
) -> T:
    r = get_redis()
    try:
        raw = await r.get(redis_key)
        if raw:
            return model.model_validate_json(raw)
    except Exception:
        logger.debug("Redis unavailable for GET %s — fetching live", redis_key)
        return await loader()

    fresh = await loader()
    try:
        await r.set(redis_key, fresh.model_dump_json(), ex=ttl_s)
    except Exception:
        logger.debug("Redis unavailable for SET %s — continuing without cache", redis_key)
    return fresh
