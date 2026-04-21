from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

Strategy = Literal["rsi", "macd_cross", "sma_cross", "bb_reversion"]


class Trade(BaseModel):
    model_config = ConfigDict(frozen=True)
    date: date
    action: Literal["buy", "sell"]
    price: Decimal
    pnl_pct: Decimal | None = None


class BacktestResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    ticker: str
    strategy: Strategy
    lookback_days: int
    total_return_pct: Decimal
    cagr_pct: Decimal
    sharpe_ratio: Decimal | None
    max_drawdown_pct: Decimal
    win_rate_pct: Decimal
    total_trades: int
    trades: list[Trade]
    disclaimer: str = (
        "Backtest results reflect past performance on a single name. "
        "No transaction costs, slippage, or survivorship bias correction applied."
    )
