from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Literal

from anthropic import AsyncAnthropic
from pydantic import BaseModel, ConfigDict, Field

from backend.app.config import get_settings
from backend.app.supabase_client import get_supabase
from backend.trading.alpaca_trader import get_open_positions, _get_client as _get_alpaca_client

_anthropic: AsyncAnthropic | None = None


def _get_anthropic() -> AsyncAnthropic:
    global _anthropic
    if _anthropic is None:
        _anthropic = AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    return _anthropic

logger = logging.getLogger(__name__)


class TradePattern(BaseModel):
    model_config = ConfigDict(frozen=True)

    pattern: str = Field(description="Name of the identified pattern")
    frequency: int = Field(description="How many losing trades show this pattern")
    avg_loss_pct: float = Field(description="Average loss percentage for this pattern")
    description: str = Field(description="Detailed explanation of why this pattern causes losses")
    fix: str = Field(description="Concrete actionable fix — threshold change, filter to add, condition to avoid")


class ThresholdAdjustment(BaseModel):
    model_config = ConfigDict(frozen=True)

    parameter: str = Field(description="Parameter name, e.g. 'min_conviction_score', 'min_upside_pct', 'stop_loss_pct'")
    current_value: str | int | float = Field(description="Current value")
    suggested_value: str | int | float = Field(description="Suggested new value")
    rationale: str = Field(description="Why this change would reduce losses")


class LossAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True)

    analyzed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    total_positions_reviewed: int
    losing_positions: int
    avg_unrealized_pnl_pct: float
    patterns: list[TradePattern]
    threshold_adjustments: list[ThresholdAdjustment]
    overall_assessment: str = Field(description="2-3 sentence plain-English summary of what's going wrong and the single most important fix")
    market_regime_note: str = Field(description="Whether current market conditions are unfavorable for the strategy and should cause a pause")


def _get_account_activities(lookback_days: int = 30) -> list[dict]:
    """Fetch filled orders from Alpaca within lookback window."""
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        client = _get_alpaca_client()
        since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        req = GetOrdersRequest(
            status=QueryOrderStatus.CLOSED,
            after=since,
            limit=100,
        )
        orders = client.get_orders(filter=req)
        return [
            {
                "symbol": o.symbol,
                "side": str(o.side.value) if hasattr(o.side, "value") else str(o.side),
                "filled_qty": str(o.filled_qty),
                "filled_avg_price": str(o.filled_avg_price),
                "status": str(o.status.value) if hasattr(o.status, "value") else str(o.status),
                "submitted_at": str(o.submitted_at),
                "filled_at": str(o.filled_at),
                "order_class": str(o.order_class) if o.order_class else "simple",
                "legs": [
                    {"side": str(l.side), "status": str(l.status), "filled_avg_price": str(l.filled_avg_price)}
                    for l in (o.legs or [])
                ],
            }
            for o in orders
        ]
    except Exception as e:
        logger.warning("could not fetch account activities: %s", e)
        return []


def _get_recent_trades_from_supabase(lookback_days: int = 30) -> list[dict]:
    """Fetch recent paper trades from Supabase."""
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        resp = get_supabase().table("paper_trades").select("*").gte("created_at", since).execute()
        return resp.data or []
    except Exception as e:
        logger.warning("could not fetch paper trades: %s", e)
        return []


async def analyze_losses(lookback_days: int = 30) -> LossAnalysis:
    """
    Ask Claude to analyze losing positions and trade patterns,
    then suggest concrete parameter adjustments to reduce future losses.
    """
    # Gather data concurrently
    positions_task = asyncio.create_task(get_open_positions())
    activities_task = asyncio.create_task(asyncio.to_thread(_get_account_activities, lookback_days))
    trades_task = asyncio.create_task(asyncio.to_thread(_get_recent_trades_from_supabase, lookback_days))

    positions_raw, activities, supabase_trades = await asyncio.gather(
        positions_task, activities_task, trades_task, return_exceptions=True
    )

    positions = positions_raw if isinstance(positions_raw, list) else []
    if isinstance(activities, Exception):
        activities = []
    if isinstance(supabase_trades, Exception):
        supabase_trades = []

    losing_positions = [p for p in positions if float(p.get("unrealized_pl", 0)) < 0]
    avg_pnl_pct = (
        sum(float(p.get("unrealized_plpc", 0)) for p in positions) / len(positions) * 100
        if positions else 0.0
    )

    context = {
        "open_positions": positions,
        "losing_positions_count": len(losing_positions),
        "avg_unrealized_pnl_pct": round(avg_pnl_pct, 2),
        "recent_filled_orders_last_N_days": activities,
        "supabase_trade_log_last_N_days": supabase_trades,
        "pipeline_parameters": {
            "min_upside_pct": 10,
            "min_conviction_score": 5,
            "position_size_usd": 1000,
            "default_stop_loss_pct": "from Claude signal",
            "default_target_pct": "from Claude signal",
            "strategy": "swing (1D+4H+1H) or day (4H+1H+15m)",
        },
    }

    prompt = f"""You are a quantitative risk manager reviewing a paper trading system that automatically enters \
positions based on: (1) 13F institutional conviction screening, (2) DCF upside gate ≥10%, \
(3) Claude multi-timeframe trade signal.

Here is the current state of the portfolio and recent trade history:

<portfolio_data>
{json.dumps(context, indent=2, default=str)}
</portfolio_data>

Your job:
1. Identify concrete patterns in the losing trades (e.g. "high-beta names in down-market", \
"low-conviction scores near threshold", "signals taken during earnings week", \
"stop too tight for volatility regime", "long signals in sector downtrend")
2. Propose specific threshold adjustments with exact numbers
3. Assess whether the current market regime is hostile to this strategy

Be specific and data-driven. If there are no losing trades, say so clearly and rate the system as healthy."""

    response = await _get_anthropic().messages.parse(
        model="claude-opus-4-7",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
        output_format=LossAnalysis,
    )
    # response.content[0] is a ToolUseBlock; .parsed holds the Pydantic model
    analysis: LossAnalysis = response.content[0].parsed  # type: ignore[union-attr]
    return LossAnalysis(
        analyzed_at=datetime.now(timezone.utc).isoformat(),
        total_positions_reviewed=analysis.total_positions_reviewed,
        losing_positions=analysis.losing_positions,
        avg_unrealized_pnl_pct=analysis.avg_unrealized_pnl_pct,
        patterns=analysis.patterns,
        threshold_adjustments=analysis.threshold_adjustments,
        overall_assessment=analysis.overall_assessment,
        market_regime_note=analysis.market_regime_note,
    )
