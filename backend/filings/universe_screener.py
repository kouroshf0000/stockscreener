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

_RSI_OVERSOLD = Decimal("50")
_RSI_OVERBOUGHT = Decimal("50")
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


def _fetch_dax40() -> list[str]:
    """DAX 40 tickers already in yfinance format (ADS.DE, AIR.PA, etc.)."""
    try:
        html = _wiki_html("https://en.wikipedia.org/wiki/DAX")
        tables = pd.read_html(io.StringIO(html), header=0)
        for df in tables:
            if "Ticker" in df.columns:
                return df["Ticker"].dropna().str.strip().tolist()
        return []
    except Exception as e:
        logger.warning("DAX wiki fetch failed: %s", e)
        return []


def _fetch_ftse100() -> list[str]:
    """FTSE 100 tickers — Wikipedia TIDMs need .L suffix for yfinance.
    TIDMs with dots (e.g. BT.A) must use hyphens in yfinance (BT-A.L)."""
    try:
        html = _wiki_html("https://en.wikipedia.org/wiki/FTSE_100")
        tables = pd.read_html(io.StringIO(html), header=0)
        for df in tables:
            if "Ticker" in df.columns:
                tickers = df["Ticker"].dropna().str.strip().tolist()
                return [f"{t.replace('.', '-')}.L" if not t.endswith(".L") else t for t in tickers]
        return []
    except Exception as e:
        logger.warning("FTSE100 wiki fetch failed: %s", e)
        return []


def _passes_long(snap: TechnicalSnapshot | None) -> bool:
    if snap is None:
        return False
    if snap.rsi_14 is None or snap.rsi_14 >= _RSI_OVERSOLD:
        return False
    if snap.tv_recommendation not in _PASS_TV:
        return False
    return True


def _passes_short(snap: TechnicalSnapshot | None) -> bool:
    if snap is None:
        return False
    if snap.rsi_14 is None or snap.rsi_14 <= _RSI_OVERBOUGHT:
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
    sp500, ndx, dax, ftse = await asyncio.gather(
        asyncio.to_thread(_fetch_sp500),
        asyncio.to_thread(_fetch_ndx),
        asyncio.to_thread(_fetch_dax40),
        asyncio.to_thread(_fetch_ftse100),
    )
    all_tickers = sp500 + ndx + dax + ftse
    universe = list(dict.fromkeys(all_tickers))
    logger.info("universe sources | sp500=%d ndx=%d dax=%d ftse=%d unique=%d",
                len(sp500), len(ndx), len(dax), len(ftse), len(universe))
    return universe


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
    tv_snapshot: dict | None = None
    if snap.tv_recommendation is not None:
        tv_snapshot = {
            "recommendation": snap.tv_recommendation,
            "rsi": float(snap.rsi_14) if snap.rsi_14 else None,
            "macd_macd": float(snap.macd) if snap.macd else None,
            "macd_signal": float(snap.macd_signal) if snap.macd_signal else None,
            "ema_50": float(snap.sma_50) if snap.sma_50 else None,
            "ema_200": float(snap.sma_200) if snap.sma_200 else None,
            "sma_50": float(snap.sma_50) if snap.sma_50 else None,
            "sma_200": float(snap.sma_200) if snap.sma_200 else None,
            "bb_upper": float(snap.bb_upper) if snap.bb_upper else None,
            "bb_lower": float(snap.bb_lower) if snap.bb_lower else None,
            "bb_pct_b": float(snap.bb_pct_b) if snap.bb_pct_b else None,
            "adx": float(snap.adx) if snap.adx else None,
            "atr": float(snap.atr) if snap.atr else None,
            "close": float(snap.price),
            "patterns": snap.patterns,
        }
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
        tv_snapshot=tv_snapshot,
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

    tech_sem = asyncio.Semaphore(4)
    snaps = await asyncio.gather(
        *[_tech_screen_one(t, tech_sem, direction="long") for t in universe]
    )

    passed: list[tuple[str, TechnicalSnapshot]] = [
        (t, s) for t, s in zip(universe, snaps) if s is not None
    ]
    logger.info("universe_screen | long_tech_pass=%d/%d", len(passed), len(universe))

    passed.sort(key=lambda x: float(x[1].rsi_14 or 99))
    dcf_batch = passed[:max_dcf]

    rows: list[ConvictionScreenRow] = []
    for rank, (ticker, snap) in enumerate(dcf_batch, start=1):
        upside, implied, current, status = await _safe_valuate(ticker, timeout=90.0)
        if status != "ok" or upside is None or upside < min_upside_pct or upside > Decimal("2.0"):
            logger.debug("universe_long_dcf skip %s | status=%s upside=%s", ticker, status, upside)
            continue
        logger.info("universe_long_pass %s | upside=%.1f%% rsi=%.1f", ticker, float(upside) * 100, float(snap.rsi_14 or 0))
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

    tech_sem = asyncio.Semaphore(4)
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

    rows: list[ConvictionScreenRow] = []
    for rank, (ticker, snap) in enumerate(dcf_batch, start=1):
        upside, implied, current, status = await _safe_valuate(ticker, timeout=90.0)
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
