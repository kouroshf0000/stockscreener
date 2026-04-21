from __future__ import annotations

from datetime import datetime

import pytest

from backend.news import engine as news_engine
from backend.news.engine import NewsItem, NewsSentiment


def test_parse_news_items() -> None:
    raw = [
        {
            "content": {
                "title": "Company beats earnings",
                "provider": {"displayName": "Bloomberg"},
                "pubDate": "2026-04-16T00:00:00Z",
                "clickThroughUrl": {"url": "https://example.com/a"},
            }
        },
        {"title": "Missing content", "providerPublishTime": 1_700_000_000, "link": "https://example.com/b"},
    ]

    class _T:
        news = raw

    import yfinance as yf

    orig = yf.Ticker

    def _fake(_sym: str) -> _T:
        return _T()

    yf.Ticker = _fake  # type: ignore[assignment]
    try:
        items = news_engine._fetch_news("TEST")
    finally:
        yf.Ticker = orig  # type: ignore[assignment]

    assert len(items) == 2
    assert items[0].publisher == "Bloomberg"
    assert items[0].published is not None
    assert items[1].title == "Missing content"


@pytest.mark.asyncio
async def test_fallback_when_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    s = news_engine.get_settings()
    monkeypatch.setattr(s, "anthropic_api_key", "", raising=False)

    async def _items(_s: str) -> list[NewsItem]:
        return [NewsItem(title="t", publisher=None, published=datetime.utcnow(), url=None)]

    import asyncio

    monkeypatch.setattr(news_engine, "_fetch_news", lambda _s: [])  # zero items path
    res = await news_engine.analyze_news("NONE")
    assert isinstance(res, NewsSentiment)
    assert res.source == "fallback"
    assert res.sentiment == "neutral"


@pytest.mark.asyncio
async def test_haiku_path_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    s = news_engine.get_settings()
    monkeypatch.setattr(s, "anthropic_api_key", "sk-test", raising=False)

    monkeypatch.setattr(
        news_engine,
        "_fetch_news",
        lambda _s: [NewsItem(title="Beat and raise", publisher="Bloomberg", published=None, url=None)],
    )

    async def _fake_score(ticker: str, items: list[NewsItem]) -> NewsSentiment:
        from datetime import date

        return NewsSentiment(
            ticker=ticker,
            as_of=date.today(),
            items_reviewed=len(items),
            sentiment="bullish",
            score=2,
            catalysts=["Q4 beat"],
            concerns=[],
            summary="Constructive.",
            source="haiku",
        )

    monkeypatch.setattr(news_engine, "_score_with_haiku", _fake_score)
    res = await news_engine.analyze_news("TEST")
    assert res.sentiment == "bullish"
    assert res.source == "haiku"
    assert res.score == 2
