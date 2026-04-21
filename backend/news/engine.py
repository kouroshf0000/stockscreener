from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone
from typing import Any, Literal

import yfinance as yf
from anthropic import AsyncAnthropic
from pydantic import BaseModel, ConfigDict

from backend.app.cache import get_redis
from backend.app.config import get_settings
from backend.data_providers.cache import key
from backend.nlp.persona import ANALYST_PERSONA

Sentiment = Literal["bullish", "neutral", "bearish"]


class NewsItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    title: str
    publisher: str | None
    published: datetime | None
    url: str | None


class NewsSentiment(BaseModel):
    model_config = ConfigDict(frozen=True)
    ticker: str
    as_of: date
    items_reviewed: int
    sentiment: Sentiment
    score: int
    catalysts: list[str]
    concerns: list[str]
    summary: str
    source: Literal["haiku", "fallback"] = "haiku"


NEWS_SYSTEM_PROMPT = (
    ANALYST_PERSONA
    + """

Task: Read recent news headlines for a ticker and return a compact institutional-grade sentiment assessment.

Output ONLY valid JSON matching:
{
  "sentiment": "bullish" | "neutral" | "bearish",
  "score": -3..3,        # -3 = deeply bearish, 0 = neutral, +3 = deeply bullish
  "catalysts": ["<= 3 near-term positive drivers"],
  "concerns": ["<= 3 risks or red flags"],
  "summary": "one-sentence net read"
}

Calibrate strictly. Promotional headlines from the company should not drive a bullish rating.
Macroeconomic news should only affect the score if materially idiosyncratic to this ticker."""
)


def _fetch_news(symbol: str) -> list[NewsItem]:
    try:
        t = yf.Ticker(symbol)
        raw = getattr(t, "news", None) or []
    except Exception:
        return []
    items: list[NewsItem] = []
    for entry in raw[:15]:
        content: dict[str, Any] = entry.get("content") or entry
        title = content.get("title") or entry.get("title")
        if not title:
            continue
        publisher = (
            (content.get("provider") or {}).get("displayName")
            if isinstance(content.get("provider"), dict)
            else content.get("publisher")
        )
        pub_time = content.get("pubDate") or entry.get("providerPublishTime")
        pub_dt: datetime | None = None
        if isinstance(pub_time, (int, float)):
            pub_dt = datetime.fromtimestamp(pub_time, tz=timezone.utc)
        elif isinstance(pub_time, str):
            try:
                pub_dt = datetime.fromisoformat(pub_time.replace("Z", "+00:00"))
            except ValueError:
                pub_dt = None
        url = (
            (content.get("clickThroughUrl") or {}).get("url")
            if isinstance(content.get("clickThroughUrl"), dict)
            else content.get("link") or entry.get("link")
        )
        items.append(NewsItem(title=title, publisher=publisher, published=pub_dt, url=url))
    return items


def _fallback(ticker: str, items: list[NewsItem]) -> NewsSentiment:
    return NewsSentiment(
        ticker=ticker.upper(),
        as_of=date.today(),
        items_reviewed=len(items),
        sentiment="neutral",
        score=0,
        catalysts=[],
        concerns=[],
        summary="No live sentiment available; defaulted to neutral.",
        source="fallback",
    )


async def _score_with_haiku(ticker: str, items: list[NewsItem]) -> NewsSentiment:
    settings = get_settings()
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    headlines = "\n".join(
        f"- [{(i.published.date().isoformat() if i.published else 'n/d')}] "
        f"{i.title} ({i.publisher or 'unknown'})"
        for i in items[:15]
    )
    resp = await client.messages.create(
        model=settings.risk_model,
        max_tokens=500,
        temperature=0,
        system=[{"type": "text", "text": NEWS_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[
            {
                "role": "user",
                "content": f"Ticker: {ticker}\n\nRecent headlines:\n{headlines}",
            }
        ],
    )
    chunks = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
    raw = "".join(chunks).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON in response")
    data = json.loads(raw[start : end + 1])
    sentiment = data.get("sentiment", "neutral")
    if sentiment not in ("bullish", "neutral", "bearish"):
        sentiment = "neutral"
    score = int(data.get("score", 0))
    score = max(-3, min(3, score))
    return NewsSentiment(
        ticker=ticker.upper(),
        as_of=date.today(),
        items_reviewed=len(items),
        sentiment=sentiment,
        score=score,
        catalysts=list(data.get("catalysts", []))[:3],
        concerns=list(data.get("concerns", []))[:3],
        summary=data.get("summary", ""),
        source="haiku",
    )


async def analyze_news(ticker: str) -> NewsSentiment:
    settings = get_settings()
    sym = ticker.upper()
    r = get_redis()
    cache_key = key("news", sym, date.today().isoformat())
    try:
        cached = await r.get(cache_key)
        if cached:
            return NewsSentiment.model_validate_json(cached)
    except Exception:
        pass

    items = await asyncio.to_thread(_fetch_news, sym)
    if not items or not settings.anthropic_api_key:
        out = _fallback(sym, items)
        try:
            await r.set(cache_key, out.model_dump_json(), ex=settings.cache_ttl_haiku_s)
        except Exception:
            pass
        return out

    try:
        out = await _score_with_haiku(sym, items)
    except Exception:
        out = _fallback(sym, items)

    try:
        await r.set(cache_key, out.model_dump_json(), ex=settings.cache_ttl_haiku_s)
    except Exception:
        pass
    return out
