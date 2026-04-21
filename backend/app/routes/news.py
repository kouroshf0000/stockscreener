from fastapi import APIRouter

from backend.news.engine import NewsSentiment, analyze_news

router = APIRouter(prefix="/api/v1", tags=["news"])


@router.get("/news/{ticker}", response_model=NewsSentiment)
async def get_news(ticker: str) -> NewsSentiment:
    return await analyze_news(ticker)
