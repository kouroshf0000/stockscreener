from fastapi import APIRouter, HTTPException

from backend.data_providers.fred_client import fetch_risk_free_rate
from backend.data_providers.models import Fundamentals, Quote, RiskFreeRate
from backend.data_providers.yfinance_client import fetch_fundamentals, fetch_quote

router = APIRouter(prefix="/api/v1", tags=["fundamentals"])


@router.get("/fundamentals/{ticker}", response_model=Fundamentals)
async def get_fundamentals(ticker: str) -> Fundamentals:
    try:
        return await fetch_fundamentals(ticker)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"upstream error: {e}") from e


@router.get("/quote/{ticker}", response_model=Quote)
async def get_quote(ticker: str) -> Quote:
    try:
        return await fetch_quote(ticker)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"upstream error: {e}") from e


@router.get("/risk-free-rate", response_model=RiskFreeRate)
async def get_rf() -> RiskFreeRate:
    return await fetch_risk_free_rate()
