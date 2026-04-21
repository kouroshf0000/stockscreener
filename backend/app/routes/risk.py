from fastapi import APIRouter

from backend.nlp.models import RiskOutput
from backend.nlp.risk_analyzer import analyze_risk

router = APIRouter(prefix="/api/v1", tags=["risk"])


@router.get("/risk/{ticker}", response_model=RiskOutput)
async def get_risk(ticker: str, include_quarterly: bool = False) -> RiskOutput:
    return await analyze_risk(ticker, include_quarterly=include_quarterly)
