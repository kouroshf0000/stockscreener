"""
SEC XBRL companyfacts API client.

Pulls 10-year annual revenue history and segment data directly from SEC's
structured XBRL data — more reliable than yfinance scraping and gives 10Y
history vs yfinance's 4Y.

No API key required. Rate-limit: ~10 req/s per the SEC fair-use policy.
"""
from __future__ import annotations

import logging
from decimal import Decimal

import httpx

from backend.data_providers.cache import cached, key
from backend.app.config import get_settings

logger = logging.getLogger(__name__)

_XBRL_BASE = "https://data.sec.gov/api/xbrl/companyfacts"
_HEADERS = {
    "User-Agent": "stock-screener/1.0 kouroshf08@gmail.com",
    "Accept-Encoding": "gzip",
}

# Revenue concepts to try in priority order
_REVENUE_CONCEPTS = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
]

# Operating income concepts
_OPINCOME_CONCEPTS = [
    "OperatingIncomeLoss",
]

# Net income concepts
_NETINCOME_CONCEPTS = [
    "NetIncomeLoss",
    "NetIncome",
]


def _extract_annual(units_usd: list[dict]) -> dict[int, Decimal]:
    """Extract most-recent 10-K value per fiscal year from a XBRL units list."""
    annual: dict[int, dict] = {}
    for entry in units_usd:
        if entry.get("form") not in ("10-K", "10-K/A"):
            continue
        if entry.get("fp") != "FY":
            continue
        fy = entry.get("fy")
        if not fy:
            continue
        filed = entry.get("filed", "")
        if fy not in annual or filed > annual[fy].get("filed", ""):
            annual[fy] = entry

    result: dict[int, Decimal] = {}
    for fy in sorted(annual.keys(), reverse=True)[:10]:
        try:
            result[fy] = Decimal(str(annual[fy]["val"]))
        except Exception:
            pass
    return result


async def fetch_xbrl_financials(cik: str) -> dict[str, dict[int, Decimal]]:
    """
    Returns {concept_key: {year: value}} for revenue, operating_income, net_income.
    All values in USD. Returns empty dicts on failure.
    """
    padded = cik.zfill(10)
    url = f"{_XBRL_BASE}/CIK{padded}.json"
    redis_key = key("xbrl_facts", cik, "v1")

    async def _fetch() -> dict:
        try:
            async with httpx.AsyncClient(timeout=30, headers=_HEADERS) as client:
                r = await client.get(url)
                r.raise_for_status()
                return r.json()
        except Exception as e:
            logger.debug("XBRL fetch failed for CIK %s: %s", cik, e)
            return {}

    # Cache the raw facts for 24h (same as fundamentals)
    facts_raw = await cached(
        redis_key,
        get_settings().cache_ttl_fundamentals_s,
        dict,
        _fetch,
    )

    us_gaap = (facts_raw.get("facts") or {}).get("us-gaap") or {}
    result: dict[str, dict[int, Decimal]] = {
        "revenue": {},
        "operating_income": {},
        "net_income": {},
    }

    for concept in _REVENUE_CONCEPTS:
        units = (us_gaap.get(concept) or {}).get("units", {}).get("USD", [])
        if units:
            result["revenue"] = _extract_annual(units)
            break

    for concept in _OPINCOME_CONCEPTS:
        units = (us_gaap.get(concept) or {}).get("units", {}).get("USD", [])
        if units:
            result["operating_income"] = _extract_annual(units)
            break

    for concept in _NETINCOME_CONCEPTS:
        units = (us_gaap.get(concept) or {}).get("units", {}).get("USD", [])
        if units:
            result["net_income"] = _extract_annual(units)
            break

    years_found = len(result["revenue"])
    if years_found:
        logger.debug("XBRL: %s revenue years fetched for CIK %s", years_found, cik)

    return result
