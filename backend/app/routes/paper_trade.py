from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from backend.app.supabase_client import get_supabase
from backend.trading.alpaca_trader import OrderResult, close_position, get_open_positions, submit_bracket_order
from backend.trading.signal_generator import SignalBatch, TradeCandidate, generate_signals

router = APIRouter(prefix="/api/v1/trade/paper", tags=["paper-trading"])


class RunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    signals: SignalBatch
    orders: list[OrderResult]
    skipped_tickers: list[str]


@router.post("/run", response_model=RunResult)
async def run_paper_trades(
    strategy: Literal["swing", "day"] = Query(default="swing"),
    top_n: int = Query(default=10, ge=1, le=20),
    exchange: str = Query(default="NASDAQ"),
    screener: str = Query(default="america"),
    dry_run: bool = Query(default=True, description="If true, generate signals but do not submit orders"),
) -> RunResult:
    """
    Full pipeline: conviction screener → DCF gate → TV technicals → Claude signal → Alpaca order.
    dry_run=true (default) returns signals without submitting orders.
    """
    try:
        batch = await generate_signals(
            strategy=strategy,
            top_n=top_n,
            exchange=exchange,
            screener=screener,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"signal generation failed: {e}") from e

    actionable = [c for c in batch.candidates if c.side != "no_trade"]
    skipped = [c.ticker for c in batch.candidates if c.side == "no_trade" and c.ticker]

    orders: list[OrderResult] = []
    if not dry_run:
        candidate_map = {c.ticker: c for c in actionable if c.ticker}
        for candidate in actionable:
            if candidate.ticker is None:
                continue
            side = "buy" if candidate.side == "long" else "sell"
            result = await submit_bracket_order(
                ticker=candidate.ticker,
                side=side,
                notional_usd=candidate.notional_usd,
                stop_loss_pct=candidate.signal.stop_loss_pct if candidate.signal.stop_loss_pct > 0 else 3.0,
                target_pct=candidate.signal.target_pct if candidate.signal.target_pct > 0 else 6.0,
            )
            orders.append(result)
            _persist_trade(result, candidate, strategy)

    return RunResult(signals=batch, orders=orders, skipped_tickers=skipped)


def _persist_trade(order: OrderResult, candidate: TradeCandidate, strategy: str) -> None:
    try:
        get_supabase().table("paper_trades").insert({
            "ticker": order.ticker,
            "side": order.side,
            "notional_usd": float(order.notional_usd),
            "order_id": order.order_id,
            "status": order.status,
            "strategy": strategy,
            "conviction_score": float(candidate.conviction_score),
            "upside_pct": float(candidate.upside_pct) if candidate.upside_pct else None,
            "signal_direction": candidate.signal.direction,
            "signal_confidence": candidate.signal.confidence,
            "entry_rationale": candidate.signal.entry_rationale,
            "stop_loss_pct": float(candidate.signal.stop_loss_pct) if hasattr(candidate.signal, 'stop_loss_pct') else None,
            "target_pct": float(candidate.signal.target_pct) if hasattr(candidate.signal, 'target_pct') else None,
            "stop_price": result.stop_price,
            "target_price": result.target_price,
        }).execute()
    except Exception:
        pass  # ledger write failure never blocks order flow


@router.get("/positions", response_model=list[dict])
async def paper_positions() -> list[dict]:
    """List all open positions in the Alpaca paper account."""
    try:
        return await get_open_positions()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"alpaca positions failed: {e}") from e


@router.delete("/positions/{ticker}", response_model=OrderResult)
async def close_paper_position(ticker: str) -> OrderResult:
    """Close the full open position for a ticker at market."""
    try:
        return await close_position(ticker)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"close position failed: {e}") from e


@router.post("/analyze", response_model=dict)
async def analyze_paper_losses() -> dict:
    """Ask Claude to analyze losing positions and suggest parameter adjustments."""
    try:
        from backend.trading.loss_analyzer import analyze_losses
        analysis = await analyze_losses(lookback_days=30)
        return analysis.model_dump()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"analysis failed: {e}") from e
