from fastapi import APIRouter, HTTPException

from backend.valuation.engine import ValuationBundle, valuate
from backend.valuation.models import Assumptions

router = APIRouter(prefix="/api/v1", tags=["valuation"])


@router.post("/valuate/{ticker}", response_model=ValuationBundle)
async def post_valuate(
    ticker: str,
    assumptions: Assumptions | None = None,
    include_monte_carlo: bool = False,
) -> ValuationBundle:
    try:
        return await valuate(ticker, assumptions, include_monte_carlo)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"valuation failed: {e}") from e
