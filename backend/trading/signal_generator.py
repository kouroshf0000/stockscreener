from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.filings.conviction_screener import ConvictionScreenRow, run_conviction_screener
from backend.filings.universe_screener import run_universe_screen
from backend.nlp.equity_researcher import ReasonedTradeSignal, reason_trade_signal
from backend.technicals.tv_enrichment import fetch_tv_multiframe

logger = logging.getLogger(__name__)

_MIN_UPSIDE_PCT_13F = Decimal("10")       # DCF upside gate for 13F conviction candidates
_MIN_UPSIDE_PCT_UNIVERSE = Decimal("7")   # DCF upside gate for technical universe candidates
_MIN_CONVICTION_SCORE = Decimal("5")
_POSITION_SIZE_USD = Decimal("1000")


class TradeCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    side: Literal["long", "short", "no_trade"]
    notional_usd: Decimal
    conviction_score: Decimal
    upside_pct: Decimal | None
    signal: ReasonedTradeSignal
    skip_reason: str | None = None


async def _build_candidate(
    row: ConvictionScreenRow,
    strategy: Literal["swing", "day"],
    exchange: str,
    screener: str,
    min_upside_pct: Decimal = _MIN_UPSIDE_PCT_13F,
) -> TradeCandidate | None:
    ticker = row.ticker
    if ticker is None:
        return None

    # Gate 1: DCF upside
    if row.upside_pct is None or row.upside_pct < min_upside_pct:
        logger.debug("skip %s: upside %s < threshold", ticker, row.upside_pct)
        return TradeCandidate(
            ticker=ticker,
            side="no_trade",
            notional_usd=Decimal("0"),
            conviction_score=row.conviction_score,
            upside_pct=row.upside_pct,
            signal=_null_signal(ticker, strategy),
            skip_reason=f"upside {row.upside_pct}% below {min_upside_pct}% threshold",
        )

    # Gate 2: Conviction score
    if row.conviction_score < _MIN_CONVICTION_SCORE:
        return TradeCandidate(
            ticker=ticker,
            side="no_trade",
            notional_usd=Decimal("0"),
            conviction_score=row.conviction_score,
            upside_pct=row.upside_pct,
            signal=_null_signal(ticker, strategy),
            skip_reason=f"conviction score {row.conviction_score} below {_MIN_CONVICTION_SCORE}",
        )

    # Gate 3: Multi-timeframe technicals → Claude reasoning
    timeframes = await fetch_tv_multiframe(
        ticker=ticker, screener=screener, exchange=exchange, strategy=strategy
    )
    if not timeframes:
        return TradeCandidate(
            ticker=ticker,
            side="no_trade",
            notional_usd=Decimal("0"),
            conviction_score=row.conviction_score,
            upside_pct=row.upside_pct,
            signal=_null_signal(ticker, strategy),
            skip_reason="no TradingView data available",
        )

    signal = await reason_trade_signal(
        ticker=ticker,
        timeframes=timeframes,
        strategy=strategy,
    )

    notional = _POSITION_SIZE_USD if signal.direction != "no_trade" else Decimal("0")
    side: Literal["long", "short", "no_trade"] = signal.direction

    return TradeCandidate(
        ticker=ticker,
        side=side,
        notional_usd=notional,
        conviction_score=row.conviction_score,
        upside_pct=row.upside_pct,
        signal=signal,
    )


def _null_signal(ticker: str, strategy: Literal["swing", "day"]) -> ReasonedTradeSignal:
    return ReasonedTradeSignal(
        direction="no_trade",
        strategy_type="no_trade",
        entry_rationale="skipped before signal reasoning",
        entry_price_note="no trade",
        stop_loss_note="no trade",
        target_note="no trade",
        risk_reward_estimate=0.0,
        timeframe_alignment="not evaluated",
        key_risks=[],
        confidence="low",
        reasoning="pre-filter rejected this candidate",
    )


class SignalBatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy: Literal["swing", "day"]
    quarter: str
    candidates: list[TradeCandidate]
    actionable_count: int
    skipped_count: int


async def generate_signals(
    strategy: Literal["swing", "day"] = "swing",
    top_n: int = 10,
    exchange: str = "NASDAQ",
    screener: str = "america",
) -> SignalBatch:
    """
    Two-track pipeline:
      Track A — 13F conviction screener (top_n, DCF gate ≥10%)
      Track B — SP500+NDX technical universe (RSI<40, uptrend, BUY/STRONG_BUY, DCF gate ≥7%)
    Both tracks run concurrently; results are merged and deduplicated by ticker.
    Claude API calls run sequentially to avoid rate pressure.
    """
    screen, universe_rows = await asyncio.gather(
        run_conviction_screener(top_n=top_n),
        run_universe_screen(min_upside_pct=_MIN_UPSIDE_PCT_UNIVERSE),
    )

    # Build 13F candidates
    seen_tickers: set[str] = set()
    candidates: list[TradeCandidate] = []

    conviction_rows = [r for r in screen.rows if r.ticker is not None and r.status == "ok"]
    for row in conviction_rows:
        candidate = await _build_candidate(
            row, strategy, exchange, screener, min_upside_pct=_MIN_UPSIDE_PCT_13F
        )
        if candidate:
            if candidate.ticker:
                seen_tickers.add(candidate.ticker)
            candidates.append(candidate)

    # Build universe candidates — skip tickers already covered by 13F track
    for row in universe_rows:
        if row.ticker in seen_tickers:
            logger.debug("universe dedup skip %s (already in 13F track)", row.ticker)
            continue
        candidate = await _build_candidate(
            row, strategy, exchange, screener, min_upside_pct=_MIN_UPSIDE_PCT_UNIVERSE
        )
        if candidate:
            if candidate.ticker:
                seen_tickers.add(candidate.ticker)
            candidates.append(candidate)

    actionable = sum(1 for c in candidates if c.side != "no_trade")
    logger.info(
        "signals merged | 13f=%d universe=%d total=%d actionable=%d",
        len(conviction_rows), len(universe_rows), len(candidates), actionable,
    )

    return SignalBatch(
        strategy=strategy,
        quarter=screen.quarter,
        candidates=candidates,
        actionable_count=actionable,
        skipped_count=len(candidates) - actionable,
    )
