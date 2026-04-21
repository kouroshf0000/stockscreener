from fastapi import APIRouter, HTTPException

from backend.technicals.engine import TechnicalSnapshot, compute_technicals

router = APIRouter(prefix="/api/v1", tags=["technicals"])


@router.get("/technicals/{ticker}", response_model=TechnicalSnapshot)
async def get_technicals(ticker: str) -> TechnicalSnapshot:
    snap = await compute_technicals(ticker)
    if snap is None:
        raise HTTPException(status_code=404, detail="no price history available")
    return snap
