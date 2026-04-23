"""
Technical/fundamental universe screener — SP500 + NDX.

Long pipeline:
  1. Fetch SP500 + NDX ticker lists from Wikipedia.
  2. Run cheap technical pre-filter concurrently (RSI < 40, uptrend, BUY/STRONG_BUY).
  3. Sort survivors by most-oversold RSI, cap at max_dcf.
  4. Run DCF sequentially on the short list, keep those ≥ min_upside_pct.

Short pipeline (run_short_universe_screen):
  1. Same universe.
  2. Opposite technical filter: RSI > 60, downtrend, SELL/STRONG_SELL.
  3. Sort by most-overbought RSI, cap at max_dcf.
  4. Run DCF, keep those ≤ max_downside_pct (DCF says overvalued).
"""
from __future__ import annotations

import asyncio
import io
import logging
from decimal import Decimal

import pandas as pd
import requests

from backend.filings.conviction_screener import (
    ConvictionScreenRow,
    ValuationStatus,
    _safe_valuate,
)
from backend.technicals.engine import TechnicalSnapshot, compute_technicals

logger = logging.getLogger(__name__)

_RSI_OVERSOLD = Decimal("40")
_RSI_OVERBOUGHT = Decimal("60")
_PASS_TV = {"BUY", "STRONG_BUY"}
_SHORT_TV = {"SELL", "STRONG_SELL"}
_WIKI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; stock-screener/1.0; "
        "+https://github.com/kouroshf0000/stockscreener)"
    )
}


def _wiki_html(url: str) -> str:
    resp = requests.get(url, headers=_WIKI_HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.text


def _fetch_sp500() -> list[str]:
    try:
        html = _wiki_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        df = pd.read_html(io.StringIO(html), header=0)[0]
        return df["Symbol"].str.replace(".", "-", regex=False).dropna().tolist()
    except Exception as e:
        logger.warning("SP500 wiki fetch failed: %s", e)
        return []


def _fetch_ndx() -> list[str]:
    try:
        html = _wiki_html("https://en.wikipedia.org/wiki/Nasdaq-100")
        tables = pd.read_html(io.StringIO(html), header=0)
        for df in tables:
            for col in ("Ticker", "Symbol"):
                if col in df.columns:
                    return df[col].dropna().tolist()
        return []
    except Exception as e:
        logger.warning("NDX wiki fetch failed: %s", e)
        return []


def _passes_long(snap: TechnicalSnapshot | None) -> bool:
    if snap is None:
        return False
    if snap.rsi_14 is None or snap.rsi_14 >= _RSI_OVERSOLD:
        return False
    if snap.trend != "uptrend":
        return False
    if snap.tv_recommendation not in _PASS_TV:
        return False
    return True


def _passes_short(snap: TechnicalSnapshot | None) -> bool:
    if snap is None:
        return False
    if snap.rsi_14 is None or snap.rsi_14 <= _RSI_OVERBOUGHT:
        return False
    if snap.trend != "downtrend":
        return False
    if snap.tv_recommendation not in _SHORT_TV:
        return False
    return True


async def _tech_screen_one(
    ticker: str,
    sem: asyncio.Semaphore,
    direction: str = "long",
) -> TechnicalSnapshot | None:
    try:
        async with sem:
            snap = await compute_technicals(ticker)
        passes = _passes_long(snap) if direction == "long" else _passes_short(snap)
        return snap if passes else None
    except Exception as e:
        logger.debug("tech_screen(%s) error: %s", ticker, e)
        return None


async def _fetch_universe() -> list[str]:
    sp500, ndx = await asyncio.gather(
        asyncio.to_thread(_fetch_sp500),
        asyncio.to_thread(_fetch_ndx),
    )
    return list(dict.fromkeys(sp500 + ndx))


def _make_row(
    rank: int,
    ticker: str,
    snap: TechnicalSnapshot,
    upside: Decimal,
    implied: Decimal | None,
    current: Decimal | None,
    status: ValuationStatus,
    source: str,
) -> ConvictionScreenRow:
    return ConvictionScreenRow(
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
        source=source,
    )


async def run_universe_screen(
    min_upside_pct: Decimal = Decimal("0.07"),  # stored as fraction: 0.07 = 7%
    max_dcf: int = 30,
) -> list[ConvictionScreenRow]:
    """
    Long candidates: RSI < 40, uptrend, BUY/STRONG_BUY, DCF upside ≥ min_upside_pct.
    """
    universe = await _fetch_universe()
    logger.info("universe_screen | universe=%d tickers", len(universe))

    tech_sem = asyncio.Semaphore(8)
    snaps = await asyncio.gather(
        *[_tech_screen_one(t, tech_sem, direction="long") for t in universe]
    )

    passed: list[tuple[str, TechnicalSnapshot]] = [
        (t, s) for t, s in zip(universe, snaps) if s is not None
    ]
    logger.info("universe_screen | long_tech_pass=%d/%d", len(passed), len(universe))

    passed.sort(key=lambda x: float(x[1].rsi_14 or 99))
    dcf_batch = passed[:max_dcf]

    dcf_sem = asyncio.Semaphore(1)
    rows: list[ConvictionScreenRow] = []
    for rank, (ticker, snap) in enumerate(dcf_batch, start=1):
        upside, implied, current, status = await _safe_valuate(
            ticker, timeout=90.0, sem=dcf_sem
        )
        if status != "ok" or upside is None or upside < min_upside_pct:
            logger.debug("universe_long_dcf skip %s | status=%s upside=%s", ticker, status, upside)
            continue
        logger.info("universe_long_pass %s | upside=%.1f%% rsi=%.1f", ticker, float(upside), float(snap.rsi_14 or 0))
        rows.append(_make_row(rank, ticker, snap, upside, implied, current, status, "universe"))

    logger.info("universe_screen | long_dcf_pass=%d/%d", len(rows), len(dcf_batch))
    return rows


async def run_short_universe_screen(
    max_downside_pct: Decimal = Decimal("-0.15"),  # DCF says ≥15% overvalued
    max_dcf: int = 20,
) -> list[ConvictionScreenRow]:
    """
    Short candidates: RSI > 60, downtrend, SELL/STRONG_SELL, DCF upside ≤ max_downside_pct.
    Returns rows with negative upside_pct (overvalued = short setup).
    """
    universe = await _fetch_universe()

    tech_sem = asyncio.Semaphore(8)
    snaps = await asyncio.gather(
        *[_tech_screen_one(t, tech_sem, direction="short") for t in universe]
    )

    passed: list[tuple[str, TechnicalSnapshot]] = [
        (t, s) for t, s in zip(universe, snaps) if s is not None
    ]
    logger.info("universe_screen | short_tech_pass=%d/%d", len(passed), len(universe))

    # Most overbought first (highest RSI → strongest short setup)
    passed.sort(key=lambda x: float(x[1].rsi_14 or 0), reverse=True)
    dcf_batch = passed[:max_dcf]

    dcf_sem = asyncio.Semaphore(1)
    rows: list[ConvictionScreenRow] = []
    for rank, (ticker, snap) in enumerate(dcf_batch, start=1):
        upside, implied, current, status = await _safe_valuate(
            ticker, timeout=90.0, sem=dcf_sem
        )
        if status != "ok" or upside is None or upside > max_downside_pct:
            logger.debug("universe_short_dcf skip %s | status=%s upside=%s", ticker, status, upside)
            continue
        logger.info(
            "universe_short_pass %s | downside=%.1f%% rsi=%.1f",
            ticker, float(upside) * 100, float(snap.rsi_14 or 0),
        )
        rows.append(_make_row(rank, ticker, snap, upside, implied, current, status, "short_universe"))

    logger.info("universe_screen | short_dcf_pass=%d/%d", len(rows), len(dcf_batch))
    return rows
