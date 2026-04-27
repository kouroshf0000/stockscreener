from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.filings.conviction_screener import ConvictionScreenRow, run_conviction_screener
from backend.filings.universe_screener import run_short_universe_screen, run_universe_screen
from backend.nlp.equity_researcher import ReasonedTradeSignal, reason_trade_signal
from backend.technicals.tv_enrichment import fetch_tv_multiframe, tv_screener_exchange

logger = logging.getLogger(__name__)

_MIN_UPSIDE_PCT_13F = Decimal("0.10")       # DCF upside gate for 13F long candidates
_MIN_UPSIDE_PCT_UNIVERSE = Decimal("0.07")  # DCF upside gate for universe long candidates
_MAX_DOWNSIDE_PCT_13F = Decimal("-0.20")    # DCF downside gate for 13F short candidates (≥20% overvalued)
_MIN_CONVICTION_SCORE = Decimal("5")
_POSITION_SIZE_USD = Decimal("1000")
_MAX_CLAUDE_CALLS = 20               # hard cap: ~$0.02/call × 20 = ~$0.40 max per run


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
    direction: Literal["long", "short"] = "long",
    claude_budget: list[int] | None = None,
) -> TradeCandidate | None:
    ticker = row.ticker
    if ticker is None:
        return None

    # Gate 1: DCF gate — long needs positive upside, short needs negative (overvalued)
    if direction == "long":
        if row.upside_pct is None or row.upside_pct < min_upside_pct:
            return TradeCandidate(
                ticker=ticker,
                side="no_trade",
                notional_usd=Decimal("0"),
                conviction_score=row.conviction_score,
                upside_pct=row.upside_pct,
                signal=_null_signal(ticker, strategy),
                skip_reason=f"upside {float(row.upside_pct or 0)*100:.1f}% below {float(min_upside_pct)*100:.0f}% threshold",
            )
    else:
        # For shorts min_upside_pct is used as max_downside (a negative number)
        if row.upside_pct is None or row.upside_pct > min_upside_pct:
            return TradeCandidate(
                ticker=ticker,
                side="no_trade",
                notional_usd=Decimal("0"),
                conviction_score=row.conviction_score,
                upside_pct=row.upside_pct,
                signal=_null_signal(ticker, strategy),
                skip_reason=f"downside {float(row.upside_pct or 0)*100:.1f}% insufficient for short (need < {float(min_upside_pct)*100:.0f}%)",
            )

    # Gate 2: Conviction score (shorts from universe screener have score=5, always pass)
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

    # Gate 3: Multi-timeframe technicals (fall back to cached 1D if multiframe fails)
    tv_scr, tv_exch = tv_screener_exchange(ticker)
    timeframes = await fetch_tv_multiframe(
        ticker=ticker, screener=tv_scr, exchange=tv_exch, strategy=strategy
    )
    if not timeframes and row.tv_snapshot is not None:
        # Universe screener already fetched 1D data — use it rather than blocking
        logger.info("tv multiframe failed for %s — falling back to cached 1D snapshot", ticker)
        timeframes = {"1D": row.tv_snapshot}
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

    # Gate 4: Claude call budget check (decremented only when a real call will be made)
    if claude_budget is not None:
        if claude_budget[0] <= 0:
            return TradeCandidate(
                ticker=ticker,
                side="no_trade",
                notional_usd=Decimal("0"),
                conviction_score=row.conviction_score,
                upside_pct=row.upside_pct,
                signal=_null_signal(ticker, strategy),
                skip_reason=f"Claude call cap {_MAX_CLAUDE_CALLS} reached",
            )
        claude_budget[0] -= 1

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
    Four-track pipeline:
      Track A — 13F conviction longs   (DCF upside ≥10%)
      Track B — Universe longs         (RSI<40, uptrend, BUY/STRONG_BUY, DCF upside ≥7%)
      Track C — Universe shorts        (RSI>60, downtrend, SELL/STRONG_SELL, DCF downside ≥15%)
      Track D — 13F conviction shorts  (DCF overvalued ≥20% — evaluated by Claude for short signal)
    All screeners run concurrently; Claude calls run sequentially.
    """
    screen, universe_long_rows, universe_short_rows = await asyncio.gather(
        run_conviction_screener(top_n=top_n),
        run_universe_screen(min_upside_pct=_MIN_UPSIDE_PCT_UNIVERSE),
        run_short_universe_screen(max_downside_pct=Decimal("-0.25")),
    )

    # Let TradingView rate limits reset after ~1300 tech-screen requests before
    # firing per-candidate multiframe calls.
    await asyncio.sleep(180)

    seen_tickers: set[str] = set()
    candidates: list[TradeCandidate] = []
    claude_budget: list[int] = [_MAX_CLAUDE_CALLS]

    # Track A: 13F conviction longs (only rows with enough upside; overvalued rows go to Track D)
    conviction_rows = [
        r for r in screen.rows
        if r.ticker is not None and r.status == "ok"
        and r.upside_pct is not None and r.upside_pct >= _MIN_UPSIDE_PCT_13F
    ]
    for row in conviction_rows:
        candidate = await _build_candidate(
            row, strategy, exchange, screener,
            min_upside_pct=_MIN_UPSIDE_PCT_13F,
            direction="long",
            claude_budget=claude_budget,
        )
        if candidate:
            if candidate.ticker:
                seen_tickers.add(candidate.ticker)
            candidates.append(candidate)

    # Track B: Universe longs
    for row in universe_long_rows:
        if row.ticker in seen_tickers:
            logger.debug("universe dedup skip %s (already in 13F track)", row.ticker)
            continue
        candidate = await _build_candidate(
            row, strategy, exchange, screener,
            min_upside_pct=_MIN_UPSIDE_PCT_UNIVERSE,
            direction="long",
            claude_budget=claude_budget,
        )
        if candidate:
            if candidate.ticker:
                seen_tickers.add(candidate.ticker)
            candidates.append(candidate)

    # Track C: Universe shorts (RSI overbought + SELL signal + DCF overvalued)
    for row in universe_short_rows:
        if row.ticker in seen_tickers:
            logger.debug("short dedup skip %s (already processed)", row.ticker)
            continue
        candidate = await _build_candidate(
            row, strategy, exchange, screener,
            min_upside_pct=Decimal("-0.15"),  # used as max_downside for shorts
            direction="short",
            claude_budget=claude_budget,
        )
        if candidate:
            if candidate.ticker:
                seen_tickers.add(candidate.ticker)
            candidates.append(candidate)

    # Track D: 13F tickers that are massively overvalued → evaluate as shorts
    conviction_short_rows = [
        r for r in screen.rows
        if r.ticker is not None
        and r.status == "ok"
        and r.ticker not in seen_tickers
        and r.upside_pct is not None
        and r.upside_pct <= _MAX_DOWNSIDE_PCT_13F
    ]
    for row in conviction_short_rows:
        candidate = await _build_candidate(
            row, strategy, exchange, screener,
            min_upside_pct=_MAX_DOWNSIDE_PCT_13F,
            direction="short",
            claude_budget=claude_budget,
        )
        if candidate:
            if candidate.ticker:
                seen_tickers.add(candidate.ticker)
            candidates.append(candidate)

    claude_used = _MAX_CLAUDE_CALLS - claude_budget[0]
    actionable = sum(1 for c in candidates if c.side != "no_trade")
    actionable_longs = sum(1 for c in candidates if c.side == "long")
    actionable_shorts = sum(1 for c in candidates if c.side == "short")
    logger.info(
        "signals merged | 13f=%d universe_long=%d universe_short=%d 13f_shorts=%d "
        "total=%d actionable=%d (long=%d short=%d) claude_calls=%d/%d",
        len(conviction_rows), len(universe_long_rows), len(universe_short_rows),
        len(conviction_short_rows), len(candidates), actionable,
        actionable_longs, actionable_shorts, claude_used, _MAX_CLAUDE_CALLS,
    )

    return SignalBatch(
        strategy=strategy,
        quarter=screen.quarter,
        candidates=candidates,
        actionable_count=actionable,
        skipped_count=len(candidates) - actionable,
    )
