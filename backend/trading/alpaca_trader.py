from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Literal

from alpaca.trading.client import TradingClient
import yfinance as yf
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from alpaca.trading.requests import MarketOrderRequest, TakeProfitRequest, StopLossRequest
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
    stop_price: float | None = None
    target_price: float | None = None


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


def _submit_plain_market(
    ticker: str,
    side: Literal["buy", "sell"],
    notional_usd: Decimal,
) -> OrderResult:
    """Synchronous plain market order helper, safe to call inside asyncio.to_thread."""
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
        logger.error("alpaca plain market fallback failed %s %s $%s: %s", side, ticker, notional_usd, e)
        return OrderResult(
            ticker=ticker.upper(),
            side=side,
            notional_usd=notional_usd,
            order_id="",
            status="failed",
            error=str(e),
        )


async def submit_bracket_order(
    ticker: str,
    side: Literal["buy", "sell"],
    notional_usd: Decimal,
    stop_loss_pct: float,
    target_pct: float,
) -> OrderResult:
    """Submit a bracket market order with take-profit and stop-loss legs."""
    def _submit_bracket() -> OrderResult:
        # 1. Fetch current price via yfinance
        price = yf.Ticker(ticker.upper()).fast_info.last_price

        # 2. Fall back to plain market order if price is unavailable
        if price is None or price <= 0:
            logger.warning(
                "submit_bracket_order: could not get price for %s, falling back to plain market order",
                ticker,
            )
            return _submit_plain_market(ticker, side, notional_usd)

        # 3. Compute quantity and bracket prices
        qty = round(float(notional_usd) / price, 2)

        if side == "buy":
            stop_price = round(price * (1 - stop_loss_pct / 100), 2)
            target_price = round(price * (1 + target_pct / 100), 2)
        else:
            stop_price = round(price * (1 + stop_loss_pct / 100), 2)
            target_price = round(price * (1 - target_pct / 100), 2)

        client = _get_client()
        try:
            req = MarketOrderRequest(
                symbol=ticker.upper(),
                qty=qty,
                side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
                order_class=OrderClass.BRACKET,
                take_profit=TakeProfitRequest(limit_price=target_price),
                stop_loss=StopLossRequest(stop_price=stop_price),
            )
            order = client.submit_order(req)
            return OrderResult(
                ticker=ticker.upper(),
                side=side,
                notional_usd=notional_usd,
                order_id=str(order.id),
                status=str(order.status),
                stop_price=stop_price,
                target_price=target_price,
            )
        except Exception as e:
            logger.warning(
                "bracket order failed for %s %s $%s (falling back to plain market): %s",
                side, ticker, notional_usd, e,
            )
            # Fall back to a plain notional market order (sync, safe inside to_thread)
            return _submit_plain_market(ticker, side, notional_usd)

    return await asyncio.to_thread(_submit_bracket)


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
