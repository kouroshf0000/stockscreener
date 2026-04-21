from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from backend.technicals import engine as tech_engine
from backend.technicals.engine import _compute, _macd, _rsi


def _series(n: int = 260, start: float = 100.0, drift: float = 0.001) -> pd.Series:
    idx = pd.date_range(end=datetime.utcnow().date(), periods=n, freq="D")
    import numpy as np

    rng = np.random.default_rng(42)
    returns = rng.normal(drift, 0.01, n)
    prices = start * (1 + pd.Series(returns)).cumprod()
    return pd.Series(prices.values, index=idx)


def test_rsi_bounded() -> None:
    close = _series()
    r = _rsi(close, 14)
    assert r is not None
    assert 0 <= r <= 100


def test_macd_returns_three_values() -> None:
    close = _series()
    m, s, h = _macd(close)
    assert m is not None and s is not None and h is not None


def test_compute_snapshot_shape() -> None:
    close = _series()
    hist = pd.DataFrame({"Close": close})
    spx = pd.DataFrame({"Close": _series()})
    snap = _compute("TEST", hist, spx)
    assert snap.ticker == "TEST"
    assert snap.price > 0
    assert snap.sma_50 is not None
    assert snap.sma_200 is not None
    assert snap.w52_high is not None
    assert snap.trend in ("uptrend", "downtrend", "consolidation")


@pytest.mark.asyncio
async def test_compute_technicals_returns_none_on_empty_history(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tech_engine, "_fetch_history", lambda _s: None)
    out = await tech_engine.compute_technicals("NONE")
    assert out is None
