"""
Financial Modeling Prep (FMP) client — analyst forward estimates.

Free tier: 250 requests/day at financialmodelingprep.com/developer
Add FMP_API_KEY to .env to activate. All functions return empty/None
gracefully when the key is absent or the endpoint returns a paid-tier error.

Key endpoints used:
  /api/v3/analyst-estimates/{ticker} — forward revenue & EPS consensus
  /api/v3/analyst-stock-recommendations/{ticker} — analyst rating grades
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

import httpx

from backend.app.config import get_settings
from backend.data_providers.cache import cached, key

logger = logging.getLogger(__name__)

_BASE = "https://financialmodelingprep.com/api/v3"


async def _fmp_get(path: str, params: dict) -> list | dict | None:
    settings = get_settings()
    if not settings.fmp_api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{_BASE}{path}",
                params={**params, "apikey": settings.fmp_api_key},
            )
            r.raise_for_status()
            data = r.json()
        # FMP returns {"Error Message": "..."} for invalid/paid endpoints
        if isinstance(data, dict) and "Error Message" in data:
            logger.debug("FMP error for %s: %s", path, data["Error Message"])
            return None
        return data
    except Exception as e:
        logger.debug("FMP request failed (%s): %s", path, e)
        return None


async def fetch_analyst_estimates(ticker: str) -> dict[str, Decimal | None]:
    """
    Returns analyst forward estimates for the next fiscal year.
    Keys: analyst_revenue_next_y, analyst_eps_next_y, analyst_revenue_growth_next_y.
    All None if FMP unavailable or key absent.
    """
    sym = ticker.upper()
    redis_key = key("fmp_estimates", sym, date.today().isoformat())

    async def _load() -> dict:
        data = await _fmp_get(f"/analyst-estimates/{sym}", {"limit": 6, "period": "annual"})
        if not data or not isinstance(data, list):
            return {}

        today_year = date.today().year
        for est in data:
            est_date = est.get("date", "")
            est_year = int(est_date[:4]) if est_date and len(est_date) >= 4 else 0
            if est_year < today_year:
                continue

            result: dict[str, Decimal | None] = {}
            rev_avg = est.get("estimatedRevenueAvg")
            eps_avg = est.get("estimatedEpsAvg")
            rev_low = est.get("estimatedRevenueLow")
            rev_high = est.get("estimatedRevenueHigh")

            if rev_avg and float(rev_avg) > 0:
                result["analyst_revenue_next_y"] = Decimal(str(rev_avg))
                result["analyst_revenue_next_y_low"] = Decimal(str(rev_low)) if rev_low else None
                result["analyst_revenue_next_y_high"] = Decimal(str(rev_high)) if rev_high else None
            if eps_avg:
                result["analyst_eps_next_y"] = Decimal(str(eps_avg))

            if result:
                logger.debug("FMP estimates for %s: %s", sym, result)
                return result

        return {}

    return await cached(redis_key, get_settings().cache_ttl_fundamentals_s, dict, _load)
