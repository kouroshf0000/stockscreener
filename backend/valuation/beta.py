"""
Self-computed beta using 2-year weekly returns vs SPY (Blume-adjusted).

Why: yfinance's `.beta` field is a single scalar with unknown methodology,
stale intervals, and no Hamada re-levering. Computing it ourselves:
  - Uses 2Y of weekly adjusted close (standard IB desk methodology)
  - Applies Blume shrinkage: β_adj = 0.67 × β_raw + 0.33 × 1.0
    (pulls extreme betas toward 1.0, as Blume 1975 showed empirically)
  - Falls back gracefully to yfinance beta if history is unavailable

All data comes from yfinance — no paid APIs required.
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

import numpy as np

logger = logging.getLogger(__name__)


def _compute_beta_sync(ticker: str) -> float | None:
    try:
        import yfinance as yf
        # 2 years of weekly data
        hist = yf.download(
            [ticker, "SPY"],
            period="2y",
            interval="1wk",
            auto_adjust=True,
            progress=False,
        )
        if hist is None or hist.empty:
            return None
        closes = hist["Close"]
        if ticker not in closes.columns or "SPY" not in closes.columns:
            return None
        stock = closes[ticker].dropna()
        spy = closes["SPY"].dropna()
        # align
        aligned = stock.align(spy, join="inner")
        stock_a, spy_a = aligned
        if len(stock_a) < 30:
            return None
        # weekly returns
        r_stock = stock_a.pct_change().dropna().values
        r_spy = spy_a.pct_change().dropna().values
        # min length after pct_change
        n = min(len(r_stock), len(r_spy))
        r_stock, r_spy = r_stock[-n:], r_spy[-n:]
        cov = np.cov(r_stock, r_spy)
        var_spy = cov[1, 1]
        if var_spy <= 0:
            return None
        beta_raw = cov[0, 1] / var_spy
        # Blume shrinkage toward 1.0
        beta_adj = 0.67 * beta_raw + 0.33 * 1.0
        return float(beta_adj)
    except Exception as e:
        logger.debug("beta compute failed for %s: %s", ticker, e)
        return None


async def compute_beta(ticker: str, fallback: Decimal | None = None) -> Decimal:
    """Return Blume-adjusted 2Y weekly beta. Falls back to supplied value or 1.0."""
    beta_float = await asyncio.to_thread(_compute_beta_sync, ticker)
    if beta_float is not None and 0.1 < beta_float < 4.0:
        return Decimal(str(round(beta_float, 4)))
    return fallback if fallback is not None else Decimal("1.0")
