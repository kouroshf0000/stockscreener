"""
Technical/fundamental universe screener — SP500 + NDX.

Pipeline:
  1. Fetch SP500 + NDX ticker lists from Wikipedia.
  2. Run cheap technical pre-filter concurrently (RSI < 40, uptrend, BUY/STRONG_BUY).
  3. Sort survivors by most-oversold RSI, cap at max_dcf.
  4. Run DCF sequentially on the short list, keep those ≥ min_upside_pct.
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

import pandas as pd

from backend.filings.conviction_screener import (
    ConvictionScreenRow,
    ValuationStatus,
    _safe_valuate,
)
from backend.technicals.engine import TechnicalSnapshot, compute_technicals

logger = logging.getLogger(__name__)

_RSI_OVERSOLD = Decimal("40")
_PASS_TV = {"BUY", "STRONG_BUY"}


def _fetch_sp500() -> list[str]:
    try:
        df = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", header=0
        )[0]
        return df["Symbol"].str.replace(".", "-", regex=False).dropna().tolist()
    except Exception as e:
        logger.warning("SP500 wiki fetch failed: %s", e)
        return []


def _fetch_ndx() -> list[str]:
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/Nasdaq-100", header=0)
        for df in tables:
            for col in ("Ticker", "Symbol"):
                if col in df.columns:
                    return df[col].dropna().tolist()
        return []
    except Exception as e:
        logger.warning("NDX wiki fetch failed: %s", e)
        return []


def _passes(snap: TechnicalSnapshot | None) -> bool:
    if snap is None:
        return False
    if snap.rsi_14 is None or snap.rsi_14 >= _RSI_OVERSOLD:
        return False
    if snap.trend != "uptrend":
        return False
    if snap.tv_recommendation not in _PASS_TV:
        return False
    return True


async def _tech_screen_one(ticker: str, sem: asyncio.Semaphore) -> TechnicalSnapshot | None:
    try:
        async with sem:
            snap = await compute_technicals(ticker)
        return snap if _passes(snap) else None
    except Exception as e:
        logger.debug("tech_screen(%s) error: %s", ticker, e)
        return None


async def run_universe_screen(
    min_upside_pct: Decimal = Decimal("0.07"),  # stored as fraction: 0.07 = 7%
    max_dcf: int = 30,
) -> list[ConvictionScreenRow]:
    """
    Returns ConvictionScreenRow list (source='universe') for all tickers that
    pass the technical pre-filter and the DCF upside gate.
    """
    sp500, ndx = await asyncio.gather(
        asyncio.to_thread(_fetch_sp500),
        asyncio.to_thread(_fetch_ndx),
    )
    universe: list[str] = list(dict.fromkeys(sp500 + ndx))
    logger.info("universe_screen | universe=%d tickers", len(universe))

    # Technical pre-filter — run concurrently, semaphore=3 to avoid yfinance crumb issues
    tech_sem = asyncio.Semaphore(3)
    snaps = await asyncio.gather(*[_tech_screen_one(t, tech_sem) for t in universe])

    passed: list[tuple[str, TechnicalSnapshot]] = [
        (t, s) for t, s in zip(universe, snaps) if s is not None
    ]
    logger.info("universe_screen | tech_pass=%d/%d", len(passed), len(universe))

    # Most oversold first (lowest RSI → best pullback-in-uptrend setup)
    passed.sort(key=lambda x: float(x[1].rsi_14 or 99))
    dcf_batch = passed[:max_dcf]

    # DCF gate — sequential (semaphore=1) to avoid concurrent yfinance fundamentals calls
    dcf_sem = asyncio.Semaphore(1)
    rows: list[ConvictionScreenRow] = []
    for rank, (ticker, snap) in enumerate(dcf_batch, start=1):
        upside, implied, current, status = await _safe_valuate(
            ticker, timeout=45.0, sem=dcf_sem
        )
        if status != "ok" or upside is None or upside < min_upside_pct:
            logger.debug(
                "universe_dcf skip %s | status=%s upside=%s", ticker, status, upside
            )
            continue
        logger.info(
            "universe_dcf pass %s | upside=%.1f%% rsi=%.1f",
            ticker, float(upside), float(snap.rsi_14 or 0),
        )
        rows.append(
            ConvictionScreenRow(
                rank=rank,
                issuer=ticker,
                ticker=ticker,
                conviction_score=Decimal("5"),
                buyer_count=0,
                buyers=[],
                max_weight_pct=Decimal("0"),
                is_consensus=False,
                upside_pct=upside,
                implied_price=implied,
                current_price=current,
                status=status,
                source="universe",
            )
        )

    logger.info("universe_screen | dcf_pass=%d/%d", len(rows), len(dcf_batch))
    return rows
