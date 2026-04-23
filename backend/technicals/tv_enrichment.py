from __future__ import annotations

import asyncio
import logging
import time
from typing import Literal

from tradingview_ta import Interval, TA_Handler

logger = logging.getLogger(__name__)

_INTERVAL_MAP: dict[str, str] = {
    "1D":  Interval.INTERVAL_1_DAY,
    "4H":  Interval.INTERVAL_4_HOURS,
    "1H":  Interval.INTERVAL_1_HOUR,
    "15m": Interval.INTERVAL_15_MINUTES,
}

# yfinance ticker suffix → (TradingView screener, primary exchange)
_SUFFIX_TV: dict[str, tuple[str, str]] = {
    ".DE": ("germany",   "FWB"),
    ".PA": ("france",    "EURONEXT"),
    ".L":  ("uk",        "LSE"),
    ".AS": ("europe",    "EURONEXT"),  # Euronext Amsterdam
    ".AX": ("australia", "ASX"),
    ".TO": ("canada",    "TSX"),
    ".BO": ("india",     "BSE"),
    ".NS": ("india",     "NSE"),
}

# Exchange fallback chains per screener
_EXCHANGE_FALLBACKS: dict[str, list[str]] = {
    "america": ["NASDAQ", "NYSE", "AMEX"],
    "germany": ["FWB", "XETR"],
}

_NOT_FOUND_PHRASES = frozenset({"not found", "exchange or symbol"})


def tv_normalize(ticker: str) -> str:
    """Strip exchange suffix and convert hyphens to dots (BRK-B → BRK.B)."""
    sym = ticker
    for suffix in _SUFFIX_TV:
        if sym.endswith(suffix):
            sym = sym[: -len(suffix)]
            break
    return sym.replace("-", ".")


def tv_screener_exchange(ticker: str) -> tuple[str, str]:
    """Return (screener, primary_exchange) for a yfinance ticker."""
    for suffix, (screener, exchange) in _SUFFIX_TV.items():
        if ticker.endswith(suffix):
            return screener, exchange
    return "america", "NASDAQ"


def _build_exchange_list(screener: str, exchange: str) -> list[str]:
    fallbacks = _EXCHANGE_FALLBACKS.get(screener, [])
    return [exchange] + [e for e in fallbacks if e != exchange]


def _is_not_found(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(p in msg for p in _NOT_FOUND_PHRASES)


def _fetch_sync(ticker: str, screener: str, exchange: str, interval: str) -> dict | None:
    sym = tv_normalize(ticker)
    exchanges = _build_exchange_list(screener, exchange)

    for exch in exchanges:
        for attempt in range(2):
            try:
                handler = TA_Handler(
                    symbol=sym,
                    screener=screener,
                    exchange=exch,
                    interval=interval,
                )
                a = handler.get_analysis()
                ind = a.indicators
                patterns = [k for k, v in ind.items() if k.startswith("Candle.") and v != 0]
                return {
                    "recommendation": a.summary.get("RECOMMENDATION"),
                    "buy_signals":     a.summary.get("BUY", 0),
                    "sell_signals":    a.summary.get("SELL", 0),
                    "neutral_signals": a.summary.get("NEUTRAL", 0),
                    "rsi":             ind.get("RSI"),
                    "rsi_ema":         ind.get("RSI[1]"),
                    "macd_macd":       ind.get("MACD.macd"),
                    "macd_signal":     ind.get("MACD.signal"),
                    "ema_20":          ind.get("EMA20"),
                    "ema_50":          ind.get("EMA50"),
                    "ema_200":         ind.get("EMA200"),
                    "sma_50":          ind.get("SMA50"),
                    "sma_200":         ind.get("SMA200"),
                    "bb_upper":        ind.get("BB.upper"),
                    "bb_lower":        ind.get("BB.lower"),
                    "bb_pct_b":        ind.get("BBP"),
                    "adx":             ind.get("ADX"),
                    "atr":             ind.get("ATR"),
                    "volume":          ind.get("volume"),
                    "close":           ind.get("close"),
                    "patterns":        patterns,
                }
            except Exception as e:
                if _is_not_found(e):
                    break  # wrong exchange — try next immediately
                if attempt == 0:
                    time.sleep(1)
                else:
                    logger.debug("TV %s [%s/%s/%s]: %s", sym, screener, exch, interval, e)
    return None


async def fetch_tv_analysis(
    ticker: str,
    screener: str = "america",
    exchange: str = "NASDAQ",
) -> dict | None:
    """Single-interval (1D) analysis — used by the valuation pipeline."""
    try:
        return await asyncio.to_thread(
            _fetch_sync, ticker, screener, exchange, Interval.INTERVAL_1_DAY
        )
    except Exception as e:
        logger.debug("fetch_tv_analysis thread error for %s: %s", ticker, e)
        return None


async def fetch_tv_multiframe(
    ticker: str,
    screener: str = "america",
    exchange: str = "NASDAQ",
    strategy: Literal["swing", "day"] = "swing",
) -> dict[str, dict]:
    """
    Swing: 1D + 4H + 1H  |  Day: 4H + 1H + 15m
    Returns dict keyed by interval label — missing intervals omitted.
    """
    intervals = ["1D", "4H", "1H"] if strategy == "swing" else ["4H", "1H", "15m"]

    tasks = [
        asyncio.to_thread(_fetch_sync, ticker, screener, exchange, _INTERVAL_MAP[iv])
        for iv in intervals
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    out: dict[str, dict] = {}
    for iv, res in zip(intervals, results):
        if isinstance(res, dict) and res is not None:
            out[iv] = res
        elif isinstance(res, Exception):
            logger.debug("tv multiframe %s [%s]: %s", ticker, iv, res)

    return out
