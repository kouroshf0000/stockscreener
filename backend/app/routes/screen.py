from fastapi import APIRouter

from backend.screener.dsl import ScreenRequest, ScreenResponse
from backend.screener.engine import run_screen

router = APIRouter(prefix="/api/v1", tags=["screener"])


@router.post("/screen", response_model=ScreenResponse)
async def post_screen(req: ScreenRequest) -> ScreenResponse:
    return await run_screen(req)
