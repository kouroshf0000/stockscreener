from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from backend.data_providers.cache import cached, key
from backend.data_providers.models import RiskFreeRate


@pytest.mark.asyncio
async def test_cache_roundtrip_and_miss() -> None:
    calls = {"n": 0}

    async def loader() -> RiskFreeRate:
        calls["n"] += 1
        return RiskFreeRate(rate=Decimal("0.045"), as_of=date(2026, 4, 17), series_id="DGS10")

    k = key("test", "rf")
    a = await cached(k, 60, RiskFreeRate, loader)
    b = await cached(k, 60, RiskFreeRate, loader)
    assert a == b
    assert calls["n"] == 1
    assert a.rate == Decimal("0.045")
