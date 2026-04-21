from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from backend.app.supabase_client import get_supabase
from backend.trading.alpaca_trader import OrderResult, close_position, get_open_positions, submit_bracket_order
from backend.trading.signal_generator import generate_signals

router = APIRouter(prefix="/api/v1/trade/paper", tags=["paper-trading"])

# In-memory job store — survives the request, lost on restart (acceptable for paper trading UI)
_jobs: dict[str, dict] = {}


class JobStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: str
    status: Literal["running", "done", "error"]
    started_at: str
    finished_at: str | None = None
    signals_count: int | None = None
    orders_count: int | None = None
    error: str | None = None
    candidates: list[dict] | None = None
    orders: list[dict] | None = None


@router.post("/run", response_model=JobStatus, status_code=202)
async def run_paper_trades(
    background_tasks: BackgroundTasks,
    strategy: Literal["swing", "day"] = Query(default="swing"),
    top_n: int = Query(default=10, ge=1, le=20),
    exchange: str = Query(default="NASDAQ"),
    screener: str = Query(default="america"),
    dry_run: bool = Query(default=True),
) -> JobStatus:
    """Start the pipeline as a background job. Poll /run/{job_id} for results."""
    job_id = str(uuid.uuid4())[:8]
    started = datetime.now(timezone.utc).isoformat()
    _jobs[job_id] = {"status": "running", "started_at": started}

    background_tasks.add_task(
        _run_pipeline, job_id, strategy, top_n, exchange, screener, dry_run
    )

    return JobStatus(job_id=job_id, status="running", started_at=started)


@router.get("/run/{job_id}", response_model=JobStatus)
async def get_run_status(job_id: str) -> JobStatus:
    """Poll pipeline job status."""
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobStatus(**job)


async def _run_pipeline(
    job_id: str,
    strategy: str,
    top_n: int,
    exchange: str,
    screener: str,
    dry_run: bool,
) -> None:
    started = _jobs[job_id]["started_at"]
    try:
        batch = await generate_signals(
            strategy=strategy,
            top_n=top_n,
            exchange=exchange,
            screener=screener,
        )

        actionable = [c for c in batch.candidates if c.side != "no_trade"]
        orders: list[OrderResult] = []

        if not dry_run:
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

        _jobs[job_id] = {
            "job_id": job_id,
            "status": "done",
            "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "signals_count": len(batch.candidates),
            "orders_count": len(orders),
            "candidates": [c.model_dump() for c in batch.candidates],
            "orders": [o.model_dump() for o in orders],
        }
    except Exception as e:
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "error",
            "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        }


def _persist_trade(order: OrderResult, candidate, strategy: str) -> None:
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
            "stop_loss_pct": float(candidate.signal.stop_loss_pct) if hasattr(candidate.signal, "stop_loss_pct") else None,
            "target_pct": float(candidate.signal.target_pct) if hasattr(candidate.signal, "target_pct") else None,
            "stop_price": order.stop_price,
            "target_price": order.target_price,
        }).execute()
    except Exception:
        pass


@router.get("/positions", response_model=list[dict])
async def paper_positions() -> list[dict]:
    try:
        return await get_open_positions()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"alpaca positions failed: {e}") from e


@router.delete("/positions/{ticker}", response_model=OrderResult)
async def close_paper_position(ticker: str) -> OrderResult:
    try:
        return await close_position(ticker)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"close position failed: {e}") from e


@router.post("/analyze", response_model=dict)
async def analyze_paper_losses() -> dict:
    try:
        from backend.trading.loss_analyzer import analyze_losses
        analysis = await analyze_losses(lookback_days=30)
        return analysis.model_dump()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"analysis failed: {e}") from e
