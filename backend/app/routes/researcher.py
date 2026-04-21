from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from backend.data_providers.fred_client import fetch_risk_free_rate
from backend.data_providers.yfinance_client import fetch_fundamentals
from backend.nlp.equity_researcher import (
    ReasonedAssumptions,
    ReasonedTradeSignal,
    reason_dcf_assumptions,
    reason_trade_signal,
)
from backend.technicals.tv_enrichment import fetch_tv_multiframe
from backend.valuation.sector_profiles import get_profile

router = APIRouter(prefix="/api/v1/research", tags=["researcher"])


class ReasonedDCFResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    ticker: str
    assumptions: ReasonedAssumptions
    sector: str | None


class TradeSignalRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    ticker: str
    strategy: Literal["swing", "day"] = "swing"
    exchange: str = "NASDAQ"
    screener: str = "america"


@router.get("/dcf-assumptions/{ticker}", response_model=ReasonedDCFResponse)
async def reasoned_dcf_assumptions(ticker: str) -> ReasonedDCFResponse:
    """
    Ask Claude Opus to derive and reason through DCF assumptions
    from first principles for this ticker.
    """
    try:
        fundamentals, rfr = await _gather(ticker)
        profile = get_profile(fundamentals.sector or "")
        sector_prior = {
            "ebit_margin_prior": float(profile.ebit_margin_prior),
            "reinv_prior": float(profile.reinv_prior),
            "terminal_growth_prior": float(profile.terminal_growth_prior),
        }
        _, reasoned = await reason_dcf_assumptions(
            ticker=ticker.upper(),
            fundamentals=fundamentals,
            sector_prior=sector_prior,
            rfr=float(rfr.rate),
        )
        return ReasonedDCFResponse(
            ticker=ticker.upper(),
            assumptions=reasoned,
            sector=fundamentals.sector,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"researcher failed: {e}") from e


@router.post("/trade-signal", response_model=ReasonedTradeSignal)
async def trade_signal(req: TradeSignalRequest) -> ReasonedTradeSignal:
    """
    Fetch multi-timeframe TradingView technicals and ask Claude Opus
    to reason through a swing or day trade signal.
    """
    try:
        timeframes = await fetch_tv_multiframe(
            ticker=req.ticker.upper(),
            screener=req.screener,
            exchange=req.exchange,
            strategy=req.strategy,
        )
        if not timeframes:
            raise ValueError(f"No TradingView data available for {req.ticker}")

        return await reason_trade_signal(
            ticker=req.ticker.upper(),
            timeframes=timeframes,
            strategy=req.strategy,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"trade signal failed: {e}") from e


async def _gather(ticker: str):
    import asyncio
    return await asyncio.gather(
        fetch_fundamentals(ticker.upper()),
        fetch_risk_free_rate(),
    )
