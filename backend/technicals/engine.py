from __future__ import annotations

import asyncio
import logging
from datetime import date
from decimal import Decimal
from typing import Literal

import pandas as pd
import yfinance as yf
from pydantic import BaseModel, ConfigDict

from backend.app.cache import get_redis
from backend.app.config import get_settings
from backend.data_providers.cache import key
from backend.technicals.tv_enrichment import fetch_tv_analysis

logger = logging.getLogger(__name__)

Trend = Literal["uptrend", "downtrend", "consolidation"]
TVRecommendation = Literal["STRONG_BUY", "BUY", "NEUTRAL", "SELL", "STRONG_SELL"]


class TechnicalSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    ticker: str
    as_of: date
    price: Decimal
    sma_50: Decimal | None
    sma_200: Decimal | None
    rsi_14: Decimal | None
    macd: Decimal | None
    macd_signal: Decimal | None
    macd_hist: Decimal | None
    w52_high: Decimal | None
    w52_low: Decimal | None
    distance_from_52w_high: Decimal | None
    distance_from_52w_low: Decimal | None
    rel_strength_vs_spx: Decimal | None
    trend: Trend
    # TV-sourced fields — all optional, degrade gracefully if TV is unavailable
    tv_recommendation: TVRecommendation | None = None
    bb_upper: Decimal | None = None
    bb_lower: Decimal | None = None
    bb_pct_b: Decimal | None = None
    adx: Decimal | None = None
    atr: Decimal | None = None
    patterns: list[str] = []


def _dec(v: float | None) -> Decimal | None:
    if v is None or pd.isna(v):
        return None
    return Decimal(str(round(float(v), 6)))


def _rsi(close: pd.Series, period: int = 14) -> float | None:
    if len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    last = float(rsi.iloc[-1])
    if pd.isna(last):
        return None
    return last


def _macd(close: pd.Series) -> tuple[float | None, float | None, float | None]:
    if len(close) < 35:
        return None, None, None
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return float(macd.iloc[-1]), float(signal.iloc[-1]), float(hist.iloc[-1])


def _rel_strength(target: pd.Series, spx: pd.Series, window: int = 126) -> float | None:
    if len(target) < window + 1 or len(spx) < window + 1:
        return None
    t_ret = float(target.iloc[-1]) / float(target.iloc[-window]) - 1
    s_ret = float(spx.iloc[-1]) / float(spx.iloc[-window]) - 1
    return t_ret - s_ret


def _trend(price: float, sma50: float | None, sma200: float | None) -> Trend:
    if sma50 is None or sma200 is None:
        return "consolidation"
    if price > sma50 > sma200:
        return "uptrend"
    if price < sma50 < sma200:
        return "downtrend"
    return "consolidation"


def _fetch_history(symbol: str) -> pd.DataFrame | None:
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="1y", interval="1d", auto_adjust=True)
        if hist is None or hist.empty:
            return None
        return hist
    except Exception:
        return None


def _compute(symbol: str, hist: pd.DataFrame, spx: pd.DataFrame | None) -> TechnicalSnapshot:
    close = hist["Close"]
    last = float(close.iloc[-1])
    sma50 = float(close.tail(50).mean()) if len(close) >= 50 else None
    sma200 = float(close.tail(200).mean()) if len(close) >= 200 else None
    rsi = _rsi(close, 14)
    macd, signal, hist_val = _macd(close)
    w52_high = float(close.tail(252).max()) if len(close) >= 10 else None
    w52_low = float(close.tail(252).min()) if len(close) >= 10 else None
    rs = None
    if spx is not None and not spx.empty:
        rs = _rel_strength(close, spx["Close"])
    return TechnicalSnapshot(
        ticker=symbol.upper(),
        as_of=date.today(),
        price=Decimal(str(round(last, 4))),
        sma_50=_dec(sma50),
        sma_200=_dec(sma200),
        rsi_14=_dec(rsi),
        macd=_dec(macd),
        macd_signal=_dec(signal),
        macd_hist=_dec(hist_val),
        w52_high=_dec(w52_high),
        w52_low=_dec(w52_low),
        distance_from_52w_high=_dec((last / w52_high - 1)) if w52_high else None,
        distance_from_52w_low=_dec((last / w52_low - 1)) if w52_low else None,
        rel_strength_vs_spx=_dec(rs),
        trend=_trend(last, sma50, sma200),
    )


async def compute_technicals(ticker: str) -> TechnicalSnapshot | None:
    settings = get_settings()
    sym = ticker.upper()
    r = get_redis()
    cache_key = key("technicals", sym, date.today().isoformat())

    try:
        cached = await r.get(cache_key)
        if cached:
            return TechnicalSnapshot.model_validate_json(cached)
    except Exception:
        logger.debug("Redis unavailable for GET %s — computing live", cache_key)

    hist, spx, tv = await asyncio.gather(
        asyncio.to_thread(_fetch_history, sym),
        asyncio.to_thread(_fetch_history, "SPY"),
        fetch_tv_analysis(sym),
    )
    if hist is None or hist.empty:
        return None

    snap = _compute(sym, hist, spx)

    if tv:
        snap = snap.model_copy(update={
            "tv_recommendation": tv.get("recommendation"),
            "bb_upper": _dec(tv.get("bb_upper")),
            "bb_lower": _dec(tv.get("bb_lower")),
            "bb_pct_b": _dec(tv.get("bb_pct_b")),
            "adx": _dec(tv.get("adx")),
            "atr": _dec(tv.get("atr")),
            "patterns": tv.get("patterns", []),
        })

    try:
        await r.set(cache_key, snap.model_dump_json(), ex=settings.cache_ttl_quotes_s)
    except Exception:
        logger.debug("Redis unavailable for SET %s — continuing without cache", cache_key)

    return snap
