from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.backtester.engine import run_backtest
from backend.backtester.models import BacktestResult, Strategy

router = APIRouter(prefix="/api/v1", tags=["backtester"])


@router.get("/backtest/{ticker}", response_model=BacktestResult)
async def get_backtest(
    ticker: str,
    strategy: Strategy = Query(default="rsi"),
    lookback_days: int = Query(default=365, ge=90, le=1095),
) -> BacktestResult:
    try:
        return await run_backtest(ticker, strategy, lookback_days)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
