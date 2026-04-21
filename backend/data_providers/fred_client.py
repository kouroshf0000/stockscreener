from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.app.config import get_settings
from backend.data_providers.cache import cached, key
from backend.data_providers.models import RiskFreeRate

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
DEFAULT_SERIES = "DGS10"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=4))
async def _fetch(series_id: str) -> RiskFreeRate:
    settings = get_settings()
    if not settings.fred_api_key:
        return RiskFreeRate(rate=Decimal("0.045"), as_of=date.today(), series_id=series_id)
    params = {
        "series_id": series_id,
        "api_key": settings.fred_api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 1,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(FRED_URL, params=params)
        r.raise_for_status()
        data = r.json()
    obs = data.get("observations", [])
    if not obs or obs[0].get("value") in (None, "."):
        return RiskFreeRate(rate=Decimal("0.045"), as_of=date.today(), series_id=series_id)
    rate = Decimal(obs[0]["value"]) / Decimal(100)
    as_of = date.fromisoformat(obs[0]["date"])
    return RiskFreeRate(rate=rate, as_of=as_of, series_id=series_id)


async def fetch_risk_free_rate(series_id: str = DEFAULT_SERIES) -> RiskFreeRate:
    redis_key = key("fred", series_id, date.today().isoformat())
    return await cached(
        redis_key,
        get_settings().cache_ttl_fundamentals_s,
        RiskFreeRate,
        lambda: _fetch(series_id),
    )
