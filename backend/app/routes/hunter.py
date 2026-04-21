from fastapi import APIRouter, HTTPException

from backend.hunter.engine import run_hunt
from backend.hunter.ledger import load_all_runs
from backend.hunter.models import HunterRunReport

router = APIRouter(prefix="/api/v1", tags=["hunter"])


@router.post("/hunt", response_model=HunterRunReport)
async def post_hunt(
    universe: str = "SP500", top_n: int = 5, limit: int | None = None
) -> HunterRunReport:
    try:
        return await run_hunt(universe_name=universe, top_n=top_n, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/hunt/history", response_model=list[HunterRunReport])
async def get_history() -> list[HunterRunReport]:
    return load_all_runs()
