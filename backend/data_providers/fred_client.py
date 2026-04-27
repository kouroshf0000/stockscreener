from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.app.config import get_settings
from backend.data_providers.cache import cached, key
from backend.data_providers.models import RiskFreeRate

logger = logging.getLogger(__name__)

_FALLBACK_RFR = Decimal("0.045")

# Module-level in-memory cache keyed by (series_id, date) — used when Redis is unavailable
_daily_cache: dict[tuple[str, date], RiskFreeRate] = {}

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


_CREDIT_SPREAD_SERIES = {
    "hy_spread": "BAMLH0A0HYM2",   # ICE BofA US High Yield OAS
    "ig_spread": "BAMLC0A0CMEY",   # ICE BofA US Corp Investment Grade OAS
}


_SPREAD_CACHE_KEY = ("credit_spreads", )

async def fetch_credit_spreads() -> dict[str, Decimal]:
    """
    Returns {"hy_spread": <pct as decimal>, "ig_spread": <pct as decimal>}.
    Both expressed as fractions (e.g. 0.034 = 3.4%).
    Returns empty dict if FRED is unavailable.
    """
    today = date.today()
    # Reuse cached spreads across all tickers in a run
    cached_key = ("credit_spreads", today)
    if cached_key in _daily_cache:
        return _daily_cache[cached_key]  # type: ignore[return-value]

    results: dict[str, Decimal] = {}
    for label, series_id in _CREDIT_SPREAD_SERIES.items():
        try:
            rfr = await _fetch(series_id)
            results[label] = rfr.rate / Decimal("100") if rfr.rate > Decimal("1") else rfr.rate
        except Exception as e:
            logger.debug("credit spread fetch failed (%s): %s", series_id, e)
    _daily_cache[cached_key] = results  # type: ignore[assignment]
    return results


async def fetch_risk_free_rate(series_id: str = DEFAULT_SERIES) -> RiskFreeRate:
    today = date.today()
    cache_key = (series_id, today)
    if cache_key in _daily_cache:
        return _daily_cache[cache_key]
    try:
        redis_key = key("fred", series_id, today.isoformat())
        result = await cached(
            redis_key,
            get_settings().cache_ttl_fundamentals_s,
            RiskFreeRate,
            lambda: _fetch(series_id),
        )
        _daily_cache[cache_key] = result
        return result
    except Exception as e:
        logger.warning("FRED unavailable (%s), using fallback RFR %.1f%%", e, float(_FALLBACK_RFR) * 100)
        fallback = RiskFreeRate(rate=_FALLBACK_RFR, as_of=today, series_id=series_id)
        _daily_cache[cache_key] = fallback
        return fallback
