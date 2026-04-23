"""
Financial Modeling Prep (FMP) stable API client.

Free tier: 250 requests/day at financialmodelingprep.com/developer
Add FMP_API_KEY to .env to activate. All functions fail gracefully.

Endpoints used (stable API, not deprecated v3):
  /stable/analyst-estimates?period=FY   — 5-year revenue/EBITDA/EPS consensus
  /stable/price-target-consensus        — analyst price target high/low/median/consensus
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

import httpx

from backend.app.config import get_settings
from backend.data_providers.cache import cached, key

logger = logging.getLogger(__name__)

_BASE = "https://financialmodelingprep.com/stable"


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
        if isinstance(data, dict) and ("Error Message" in data or "message" in data):
            logger.debug("FMP error for %s: %s", path, data)
            return None
        return data
    except Exception as e:
        logger.debug("FMP request failed (%s): %s", path, e)
        return None


async def fetch_analyst_estimates(ticker: str) -> dict:
    """
    Returns forward analyst estimates keyed by field name.

    Keys populated when available:
      analyst_revenue_next_y          — next fiscal year revenue consensus (avg)
      analyst_revenue_next_y_low      — low estimate
      analyst_revenue_next_y_high     — high estimate
      analyst_eps_next_y              — next fiscal year EPS consensus
      analyst_revenue_growth_next_y   — YoY growth implied by next-year estimate
      analyst_revenue_growth_path     — list[Decimal] of annual growth rates Y1-Y5
                                        (computed from consensus revenue estimates)
      analyst_ebit_next_y             — next fiscal year EBIT consensus
      analyst_ebitda_next_y           — next fiscal year EBITDA consensus
    """
    sym = ticker.upper()
    redis_key = key("fmp_estimates_v2", sym, date.today().isoformat())

    async def _load() -> dict:
        data = await _fmp_get("/analyst-estimates", {"symbol": sym, "period": "FY", "limit": 8})
        if not data or not isinstance(data, list):
            return {}

        today_year = date.today().year

        # Sort oldest→newest, filter to future and most-recent-past year
        future = sorted(
            [e for e in data if int(e.get("date", "0")[:4]) >= today_year],
            key=lambda e: e["date"],
        )
        if not future:
            return {}

        # Most recent past year for base revenue (to compute growth)
        past = sorted(
            [e for e in data if int(e.get("date", "0")[:4]) < today_year],
            key=lambda e: e["date"],
            reverse=True,
        )
        base_rev = Decimal(str(past[0]["revenueAvg"])) if past and past[0].get("revenueAvg") else None

        result: dict = {}
        next_y = future[0]

        rev_avg = next_y.get("revenueAvg")
        rev_low = next_y.get("revenueLow")
        rev_high = next_y.get("revenueHigh")
        eps_avg = next_y.get("epsAvg")
        ebit_avg = next_y.get("ebitAvg")
        ebitda_avg = next_y.get("ebitdaAvg")
        n_analysts = next_y.get("numAnalystsRevenue", 0)

        if rev_avg and float(rev_avg) > 0:
            result["analyst_revenue_next_y"] = Decimal(str(rev_avg))
            if rev_low:
                result["analyst_revenue_next_y_low"] = Decimal(str(rev_low))
            if rev_high:
                result["analyst_revenue_next_y_high"] = Decimal(str(rev_high))
            # Forward growth vs most recent completed year
            if base_rev and base_rev > 0:
                result["analyst_revenue_growth_next_y"] = (
                    Decimal(str(rev_avg)) / base_rev - Decimal("1")
                )

        if eps_avg:
            result["analyst_eps_next_y"] = Decimal(str(eps_avg))
        if ebit_avg and float(ebit_avg) > 0:
            result["analyst_ebit_next_y"] = Decimal(str(ebit_avg))
        if ebitda_avg and float(ebitda_avg) > 0:
            result["analyst_ebitda_next_y"] = Decimal(str(ebitda_avg))

        # Build 5-year annual revenue growth path from consensus
        growth_path: list[Decimal] = []
        prev_rev = base_rev
        for est in future[:5]:
            r_avg = est.get("revenueAvg")
            if r_avg and float(r_avg) > 0 and prev_rev and prev_rev > 0:
                g = Decimal(str(r_avg)) / prev_rev - Decimal("1")
                growth_path.append(g)
                prev_rev = Decimal(str(r_avg))
            else:
                break

        if growth_path:
            result["analyst_revenue_growth_path"] = growth_path

        logger.info(
            "FMP estimates %s: Y1 rev=$%.0fB growth=%.1f%% (%d analysts, %d-year path)",
            sym,
            float(result.get("analyst_revenue_next_y", 0)) / 1e9,
            float(result.get("analyst_revenue_growth_next_y", 0)) * 100,
            n_analysts,
            len(growth_path),
        )
        return result

    return await cached(redis_key, get_settings().cache_ttl_fundamentals_s, dict, _load)


async def fetch_price_target_consensus(ticker: str) -> dict:
    """
    Returns {"fmp_target_consensus": Decimal, "fmp_target_high": Decimal,
             "fmp_target_low": Decimal, "fmp_target_median": Decimal}.
    Empty dict if unavailable.
    """
    sym = ticker.upper()
    redis_key = key("fmp_pt_v2", sym, date.today().isoformat())

    async def _load() -> dict:
        data = await _fmp_get("/price-target-consensus", {"symbol": sym})
        if not data or not isinstance(data, list) or not data[0]:
            return {}
        d = data[0]
        result = {}
        for src, dst in [
            ("targetConsensus", "fmp_target_consensus"),
            ("targetHigh", "fmp_target_high"),
            ("targetLow", "fmp_target_low"),
            ("targetMedian", "fmp_target_median"),
        ]:
            v = d.get(src)
            if v is not None:
                result[dst] = Decimal(str(v))
        return result

    return await cached(redis_key, get_settings().cache_ttl_fundamentals_s, dict, _load)
