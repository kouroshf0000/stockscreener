from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from backend.backtester.engine import (
    _compute_metrics,
    _run_strategy,
    run_backtest,
)
from backend.backtester.models import Trade


def _series(n: int = 300, start: float = 100.0, drift: float = 0.001, seed: int = 42) -> pd.Series:
    rng = np.random.default_rng(seed)
    returns = rng.normal(drift, 0.015, n)
    prices = start * np.cumprod(1 + returns)
    idx = pd.date_range(end=date.today(), periods=n, freq="D")
    return pd.Series(prices, index=idx)


def _mk_hist(series: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({"Close": series, "Open": series, "High": series, "Low": series, "Volume": 1})


def test_rsi_strategy_returns_trades() -> None:
    close = _series(300, drift=0.0, seed=7)
    trades = _run_strategy(close, "rsi")
    assert len(trades) >= 1
    buys = [t for t in trades if t.action == "buy"]
    sells = [t for t in trades if t.action == "sell"]
    assert len(buys) >= 1
    assert len(sells) >= 1


def test_macd_strategy_returns_trades() -> None:
    close = _series(300, drift=0.001, seed=10)
    trades = _run_strategy(close, "macd_cross")
    assert len(trades) >= 1


def test_sma_cross_requires_200_bars() -> None:
    close = _series(250, drift=0.001, seed=1)
    trades = _run_strategy(close, "sma_cross")
    # May produce zero trades on short series — should not raise
    assert isinstance(trades, list)


def test_bb_reversion_returns_trades() -> None:
    close = _series(300, drift=0.0, seed=99)
    trades = _run_strategy(close, "bb_reversion")
    assert isinstance(trades, list)


def test_metrics_total_return() -> None:
    trades = [
        Trade(date=date(2024, 1, 1), action="buy", price=Decimal("100")),
        Trade(date=date(2024, 3, 1), action="sell", price=Decimal("110"), pnl_pct=Decimal("10")),
        Trade(date=date(2024, 4, 1), action="buy", price=Decimal("110")),
        Trade(date=date(2024, 6, 1), action="sell", price=Decimal("121"), pnl_pct=Decimal("10")),
    ]
    close = _series(365)
    metrics = _compute_metrics(trades, close, 365)
    # Compound: 1.1 * 1.1 = 1.21 → 21% total return
    assert float(metrics["total_return_pct"]) == pytest.approx(21.0, rel=0.01)
    assert metrics["total_trades"] == 2
    assert float(metrics["win_rate_pct"]) == pytest.approx(100.0)


def test_backtest_insufficient_history_raises() -> None:
    hist = _mk_hist(_series(30))

    async def _run() -> None:
        with patch("backend.backtester.engine._fetch_history_bt", return_value=hist):
            await run_backtest("AAPL", "rsi", 365)

    import asyncio
    with pytest.raises(ValueError, match="Insufficient history"):
        asyncio.run(_run())


@pytest.mark.asyncio
async def test_run_backtest_mocked_shape() -> None:
    hist = _mk_hist(_series(300))
    with patch("backend.backtester.engine._fetch_history_bt", return_value=hist):
        result = await run_backtest("AAPL", "rsi", 365)
    assert result.ticker == "AAPL"
    assert result.strategy == "rsi"
    assert result.lookback_days == 365
    assert isinstance(result.total_return_pct, Decimal)
    assert isinstance(result.sharpe_ratio, Decimal | type(None))
    assert result.total_trades == len([t for t in result.trades if t.action == "sell"])
    assert len(result.disclaimer) > 10
