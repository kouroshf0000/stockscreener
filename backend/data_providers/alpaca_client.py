from __future__ import annotations

import asyncio
import logging
from datetime import date
from decimal import Decimal

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest

from backend.app.config import get_settings
from backend.data_providers.cache import cached, key
from backend.data_providers.models import Quote

logger = logging.getLogger(__name__)

_client: StockHistoricalDataClient | None = None


def _get_client() -> StockHistoricalDataClient | None:
    global _client
    if _client is not None:
        return _client
    settings = get_settings()
    if not settings.alpaca_api_key or not settings.alpaca_secret_key:
        return None
    _client = StockHistoricalDataClient(
        api_key=settings.alpaca_api_key,
        secret_key=settings.alpaca_secret_key,
    )
    return _client


def _fetch_sync(ticker: str) -> Quote:
    client = _get_client()
    if client is None:
        raise RuntimeError("Alpaca keys not configured")
    req = StockLatestQuoteRequest(symbol_or_symbols=ticker.upper())
    quotes = client.get_stock_latest_quote(req)
    q = quotes[ticker.upper()]
    # Use mid-price (ask + bid) / 2; fall back to ask if bid is zero
    bid = float(q.bid_price or 0)
    ask = float(q.ask_price or 0)
    price = (bid + ask) / 2 if bid > 0 and ask > 0 else ask or bid
    if price <= 0:
        raise RuntimeError(f"No valid price for {ticker}")
    return Quote(
        ticker=ticker.upper(),
        price=Decimal(str(round(price, 4))),
        volume=int(q.ask_size or 0),
        as_of=date.today(),
    )


async def fetch_quote_alpaca(ticker: str) -> Quote:
    settings = get_settings()
    sym = ticker.upper()
    redis_key = key("quote_alpaca", sym)

    async def loader() -> Quote:
        return await asyncio.to_thread(_fetch_sync, sym)

    return await cached(redis_key, settings.cache_ttl_quotes_s, Quote, loader)
