from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.app.config import get_settings
from backend.data_providers.cache import cached, key
from backend.data_providers.models import FinancialStatement, Fundamentals, Quote


def _dec(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return Decimal(str(v))
    except Exception:
        return None


def _row(df: pd.DataFrame | None, name: str, col: Any) -> Decimal | None:
    if df is None or df.empty or name not in df.index:
        return None
    try:
        return _dec(df.loc[name, col])
    except Exception:
        return None


def _build_statements(t: yf.Ticker) -> list[FinancialStatement]:
    inc = getattr(t, "income_stmt", None)
    cf = getattr(t, "cashflow", None)
    bs = getattr(t, "balance_sheet", None)
    cols = []
    for df in (inc, cf, bs):
        if df is not None and not df.empty:
            cols = list(df.columns)
            break
    statements: list[FinancialStatement] = []
    for col in cols:
        period = col.date() if hasattr(col, "date") else date.fromisoformat(str(col)[:10])
        revenue = _row(inc, "Total Revenue", col)
        op_income = _row(inc, "Operating Income", col)
        net_income = _row(inc, "Net Income", col)
        interest = _row(inc, "Interest Expense", col)
        tax_prov = _row(inc, "Tax Provision", col)
        pretax = _row(inc, "Pretax Income", col)
        tax_rate = None
        if tax_prov is not None and pretax not in (None, Decimal(0)):
            try:
                tax_rate = tax_prov / pretax
            except Exception:
                tax_rate = None
        ocf = _row(cf, "Operating Cash Flow", col)
        capex = _row(cf, "Capital Expenditure", col)
        fcf = _row(cf, "Free Cash Flow", col)
        if fcf is None and ocf is not None and capex is not None:
            fcf = ocf + capex
        da = _row(cf, "Depreciation And Amortization", col) or _row(
            inc, "Reconciled Depreciation", col
        )
        ebitda = None
        if op_income is not None and da is not None:
            ebitda = op_income + da
        nwc_change = _row(cf, "Change In Working Capital", col)
        sbc = _row(cf, "Stock Based Compensation", col)
        total_debt = _row(bs, "Total Debt", col)
        op_lease = _row(bs, "Current Capital Lease Obligation", col)
        op_lease_long = _row(bs, "Long Term Capital Lease Obligation", col)
        if op_lease is None and op_lease_long is None:
            op_lease_total = None
        else:
            op_lease_total = (op_lease or Decimal(0)) + (op_lease_long or Decimal(0))
        cash = _row(bs, "Cash And Cash Equivalents", col)
        equity = _row(bs, "Stockholders Equity", col)
        shares = _row(bs, "Ordinary Shares Number", col)
        statements.append(
            FinancialStatement(
                period_end=period,
                revenue=revenue,
                operating_income=op_income,
                net_income=net_income,
                ebitda=ebitda,
                free_cash_flow=fcf,
                operating_cash_flow=ocf,
                capex=capex,
                depreciation_and_amortization=da,
                working_capital_change=nwc_change,
                stock_based_compensation=sbc,
                total_debt=total_debt,
                cash_and_equivalents=cash,
                total_equity=equity,
                shares_outstanding=shares,
                interest_expense=interest,
                tax_rate=tax_rate,
            )
        )
    statements.sort(key=lambda s: s.period_end, reverse=True)
    return statements


def _fetch_segments(t: yf.Ticker) -> dict[str, Any]:
    """Best-effort segment revenue dict from yfinance. Empty when unavailable."""
    segs: dict[str, Any] = {}
    try:
        rev_by_seg = getattr(t, "revenue_by_geography", None)
        if rev_by_seg is not None and not rev_by_seg.empty:
            col = rev_by_seg.columns[0]
            for seg, val in rev_by_seg[col].items():
                v = _dec(val)
                if v is not None:
                    segs[str(seg)] = v
    except Exception:
        pass
    if not segs:
        try:
            rev_by_prod = getattr(t, "revenue_by_product", None)
            if rev_by_prod is not None and not rev_by_prod.empty:
                col = rev_by_prod.columns[0]
                for seg, val in rev_by_prod[col].items():
                    v = _dec(val)
                    if v is not None:
                        segs[str(seg)] = v
        except Exception:
            pass
    return segs


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=4))
def _fetch_sync(ticker: str) -> Fundamentals:
    t = yf.Ticker(ticker)
    info = getattr(t, "info", {}) or {}
    fast = getattr(t, "fast_info", None)
    price = None
    if fast is not None:
        price = _dec(getattr(fast, "last_price", None))
    if price is None:
        price = _dec(info.get("currentPrice") or info.get("regularMarketPrice"))

    statements = _build_statements(t)
    segments = _fetch_segments(t)

    # Analyst count may be int or float from yfinance
    raw_count = info.get("numberOfAnalystOpinions")
    analyst_count = int(raw_count) if raw_count is not None else None

    return Fundamentals(
        ticker=ticker.upper(),
        name=info.get("shortName") or info.get("longName"),
        sector=info.get("sector"),
        industry=info.get("industry"),
        market_cap=_dec(info.get("marketCap")),
        beta=_dec(info.get("beta")),
        price=price,
        currency=info.get("currency", "USD"),
        statements=statements,
        as_of=date.today(),
        # TTM ratios
        revenue=_dec(info.get("totalRevenue")),
        operating_margin=_dec(info.get("operatingMargins")),
        revenue_growth=_dec(info.get("revenueGrowth")),
        return_on_equity=_dec(info.get("returnOnEquity")),
        debt_to_equity=_dec(info.get("debtToEquity")),
        pe_ratio=_dec(info.get("trailingPE")),
        # Analyst consensus
        analyst_target_mean=_dec(info.get("targetMeanPrice")),
        analyst_target_high=_dec(info.get("targetHighPrice")),
        analyst_target_low=_dec(info.get("targetLowPrice")),
        analyst_count=analyst_count,
        analyst_recommendation=_dec(info.get("recommendationMean")),
        forward_pe=_dec(info.get("forwardPE")),
        forward_eps=_dec(info.get("forwardEps")),
        segments=segments,
        # Additional market signals
        short_pct_float=_dec(info.get("shortPercentOfFloat")),
        held_pct_institutions=_dec(info.get("heldPercentInstitutions")),
        earnings_growth=_dec(info.get("earningsGrowth")),
    )


async def fetch_fundamentals(ticker: str) -> Fundamentals:
    # Thin alias kept for callers that only need yfinance base data.
    return await _fetch_base_fundamentals(ticker)


async def _fetch_base_fundamentals(ticker: str) -> Fundamentals:
    settings = get_settings()
    sym = ticker.upper()
    redis_key = key("fundamentals", sym, date.today().isoformat())

    async def loader() -> Fundamentals:
        return await asyncio.to_thread(_fetch_sync, sym)

    return await cached(redis_key, settings.cache_ttl_fundamentals_s, Fundamentals, loader)


async def fetch_enriched_fundamentals(ticker: str) -> Fundamentals:
    """
    Full enrichment pipeline:
      1. yfinance base fundamentals (cached 24h)
      2. FMP analyst forward estimates (optional — needs FMP_API_KEY)
      3. SEC XBRL 10-year revenue history (free, no key)
      4. FRED credit spreads (free, needs FRED_API_KEY)
    All enrichment sources fail gracefully — base fundamentals always returned.
    """
    from backend.data_providers.fmp_client import fetch_analyst_estimates
    from backend.data_providers.sec_xbrl_client import fetch_xbrl_financials
    from backend.data_providers.fred_client import fetch_credit_spreads
    from backend.filings.discovery import resolve_cik

    base = await _fetch_base_fundamentals(ticker)
    updates: dict = {}

    # Run all enrichment sources concurrently
    fmp_task = fetch_analyst_estimates(ticker)
    spreads_task = fetch_credit_spreads()

    # CIK needed for XBRL — resolve first
    cik_res = await resolve_cik(ticker)
    if cik_res is not None:
        xbrl_task = fetch_xbrl_financials(cik_res.cik)
    else:
        import asyncio as _asyncio
        xbrl_task = _asyncio.sleep(0, result={})  # type: ignore[assignment]

    import asyncio as _asyncio
    fmp_data, spreads_data, xbrl_data = await _asyncio.gather(
        fmp_task, spreads_task, xbrl_task, return_exceptions=True
    )

    # FMP analyst forward estimates
    if isinstance(fmp_data, dict) and fmp_data:
        updates.update(fmp_data)
        # Compute forward revenue growth if we have TTM revenue
        rev_next = fmp_data.get("analyst_revenue_next_y")
        ttm_rev = base.revenue
        if rev_next and ttm_rev and ttm_rev > 0:
            updates["analyst_revenue_growth_next_y"] = (rev_next / ttm_rev) - Decimal("1")

    # FRED credit spreads
    if isinstance(spreads_data, dict):
        if "hy_spread" in spreads_data:
            updates["credit_spread_hy"] = spreads_data["hy_spread"]
        if "ig_spread" in spreads_data:
            updates["credit_spread_ig"] = spreads_data["ig_spread"]

    # SEC XBRL 10-year revenue history
    if isinstance(xbrl_data, dict):
        rev_history = xbrl_data.get("revenue", {})
        if rev_history:
            updates["xbrl_revenue_10y"] = rev_history

    if not updates:
        return base
    return base.model_copy(update=updates)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=4))
def _fetch_quote_sync(ticker: str) -> Quote:
    t = yf.Ticker(ticker)
    fast = getattr(t, "fast_info", None)
    price = _dec(getattr(fast, "last_price", None)) if fast else None
    volume = int(getattr(fast, "last_volume", 0) or 0) if fast else 0
    if price is None:
        raise RuntimeError(f"no price for {ticker}")
    return Quote(ticker=ticker.upper(), price=price, volume=volume, as_of=date.today())


async def fetch_quote(ticker: str) -> Quote:
    from backend.data_providers.alpaca_client import fetch_quote_alpaca
    from backend.app.config import get_settings as _gs
    if _gs().alpaca_api_key and _gs().alpaca_secret_key:
        try:
            return await fetch_quote_alpaca(ticker)
        except Exception:
            pass  # fall through to yfinance

    settings = get_settings()
    sym = ticker.upper()
    redis_key = key("quote", sym)

    async def loader() -> Quote:
        return await asyncio.to_thread(_fetch_quote_sync, sym)

    return await cached(redis_key, settings.cache_ttl_quotes_s, Quote, loader)
