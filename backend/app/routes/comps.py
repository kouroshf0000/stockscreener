from fastapi import APIRouter, HTTPException

from backend.comps.engine import CompsResult, run_comps

router = APIRouter(prefix="/api/v1", tags=["comps"])


@router.get("/comps/{ticker}", response_model=CompsResult)
async def get_comps(ticker: str) -> CompsResult:
    try:
        return await run_comps(ticker)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"comps failed: {e}") from e
