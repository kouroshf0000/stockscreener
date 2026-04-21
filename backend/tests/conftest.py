from __future__ import annotations

import time
from typing import Any

import pytest

from backend.app import cache as cache_mod


class FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}

    async def get(self, k: str) -> str | None:
        v = self._store.get(k)
        if v is None:
            return None
        val, exp = v
        if exp is not None and time.time() > exp:
            del self._store[k]
            return None
        return val

    async def set(self, k: str, v: str, ex: int | None = None) -> None:
        exp = time.time() + ex if ex else None
        self._store[k] = (v, exp)

    async def delete(self, *keys: str) -> int:
        n = 0
        for k in keys:
            if k in self._store:
                del self._store[k]
                n += 1
        return n


@pytest.fixture(autouse=True)
def patch_redis(monkeypatch: pytest.MonkeyPatch) -> Any:
    fake = FakeRedis()
    monkeypatch.setattr(cache_mod, "_redis", fake)
    monkeypatch.setattr(cache_mod, "get_redis", lambda: fake)
    return fake
