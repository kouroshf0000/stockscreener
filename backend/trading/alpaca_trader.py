from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Literal

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest
from pydantic import BaseModel, ConfigDict

from backend.app.config import get_settings

logger = logging.getLogger(__name__)

_client: TradingClient | None = None


def _get_client() -> TradingClient:
    global _client
    if _client is None:
        s = get_settings()
        _client = TradingClient(
            api_key=s.alpaca_api_key,
            secret_key=s.alpaca_secret_key,
            paper=s.alpaca_paper,
        )
    return _client


class OrderResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    side: Literal["buy", "sell"]
    notional_usd: Decimal
    order_id: str
    status: str
    error: str | None = None


async def submit_notional_order(
    ticker: str,
    side: Literal["buy", "sell"],
    notional_usd: Decimal,
) -> OrderResult:
    """Submit a market order by dollar notional (fractional shares supported)."""
    def _submit() -> OrderResult:
        client = _get_client()
        try:
            req = MarketOrderRequest(
                symbol=ticker.upper(),
                notional=float(notional_usd),
                side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )
            order = client.submit_order(req)
            return OrderResult(
                ticker=ticker.upper(),
                side=side,
                notional_usd=notional_usd,
                order_id=str(order.id),
                status=str(order.status),
            )
        except Exception as e:
            logger.error("alpaca order failed %s %s $%s: %s", side, ticker, notional_usd, e)
            return OrderResult(
                ticker=ticker.upper(),
                side=side,
                notional_usd=notional_usd,
                order_id="",
                status="failed",
                error=str(e),
            )

    return await asyncio.to_thread(_submit)


async def close_position(ticker: str) -> OrderResult:
    """Close the full open position for a ticker at market."""
    def _close() -> OrderResult:
        client = _get_client()
        try:
            order = client.close_position(ticker.upper())
            return OrderResult(
                ticker=ticker.upper(),
                side="sell",
                notional_usd=Decimal("0"),
                order_id=str(order.id),
                status=str(order.status),
            )
        except Exception as e:
            logger.error("alpaca close_position failed %s: %s", ticker, e)
            return OrderResult(
                ticker=ticker.upper(),
                side="sell",
                notional_usd=Decimal("0"),
                order_id="",
                status="failed",
                error=str(e),
            )

    return await asyncio.to_thread(_close)


async def get_open_positions() -> list[dict]:
    """Return all open positions from the paper account."""
    def _fetch() -> list[dict]:
        client = _get_client()
        positions = client.get_all_positions()
        return [
            {
                "ticker": p.symbol,
                "qty": str(p.qty),
                "market_value": str(p.market_value),
                "avg_entry_price": str(p.avg_entry_price),
                "unrealized_pl": str(p.unrealized_pl),
                "unrealized_plpc": str(p.unrealized_plpc),
                "side": p.side.value if hasattr(p.side, "value") else str(p.side),
            }
            for p in positions
        ]

    return await asyncio.to_thread(_fetch)
