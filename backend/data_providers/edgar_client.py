from __future__ import annotations

from datetime import date
from typing import NamedTuple

from backend.app.cache import get_redis
from backend.app.config import get_settings
from backend.data_providers.cache import key
from backend.data_providers.models import FilingRef
from backend.filings.discovery import latest as _latest_filing
from backend.filings.discovery import resolve_cik
from backend.filings.risk_factors import fetch_risk_factors_universal
from backend.filings.taxonomy import ANNUAL_FORMS

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"


class ExtractResult(NamedTuple):
    text: str | None
    reason: str
    filing: FilingRef | None


async def get_cik(ticker: str) -> str:
    res = await resolve_cik(ticker)
    if res is None:
        raise LookupError(f"CIK not found for {ticker}")
    return res.cik


async def latest_filing(ticker: str, form: str | list[str] = "10-K") -> FilingRef | None:
    forms: tuple[str, ...] = (form,) if isinstance(form, str) else tuple(form)
    return await _latest_filing(ticker, forms)


async def fetch_risk_factors_with_diagnostics(
    ticker: str, include_quarterly: bool = False
) -> ExtractResult:
    trace = await fetch_risk_factors_universal(ticker, include_quarterly=include_quarterly)
    return ExtractResult(trace.text, trace.reason, trace.filing)


async def fetch_risk_factors(ticker: str) -> str | None:
    result = await fetch_risk_factors_with_diagnostics(ticker)
    return result.text


async def fetch_risk_factors_cached(ticker: str) -> str | None:
    r = get_redis()
    sym = ticker.upper()
    redis_key = key("edgar", "risk", sym, date.today().isoformat())
    try:
        raw = await r.get(redis_key)
        if raw is not None:
            return raw or None
    except Exception:
        pass
    text = await fetch_risk_factors(sym)
    try:
        await r.set(redis_key, text or "", ex=get_settings().cache_ttl_fundamentals_s)
    except Exception:
        pass
    return text


async def fetch_risk_factors_cached_with_diagnostics(ticker: str) -> ExtractResult:
    r = get_redis()
    sym = ticker.upper()
    redis_key = key("edgar", "risk", sym, date.today().isoformat())
    try:
        raw = await r.get(redis_key)
        if raw is not None:
            return ExtractResult(
                text=raw or None,
                reason="cached" if raw else "cached_empty",
                filing=None,
            )
    except Exception:
        pass
    result = await fetch_risk_factors_with_diagnostics(sym)
    try:
        await r.set(redis_key, result.text or "", ex=get_settings().cache_ttl_fundamentals_s)
    except Exception:
        pass
    return result
