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
    return Fundamentals(
        ticker=ticker.upper(),
        name=info.get("shortName") or info.get("longName"),
        sector=info.get("sector"),
        industry=info.get("industry"),
        market_cap=_dec(info.get("marketCap")),
        beta=_dec(info.get("beta")),
        price=price,
        currency=info.get("currency", "USD"),
        statements=_build_statements(t),
        as_of=date.today(),
    )


async def fetch_fundamentals(ticker: str) -> Fundamentals:
    settings = get_settings()
    sym = ticker.upper()
    redis_key = key("fundamentals", sym, date.today().isoformat())

    async def loader() -> Fundamentals:
        return await asyncio.to_thread(_fetch_sync, sym)

    return await cached(redis_key, settings.cache_ttl_fundamentals_s, Fundamentals, loader)


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
