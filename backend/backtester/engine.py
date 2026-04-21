from __future__ import annotations

import asyncio
import math
from datetime import date
from decimal import Decimal

import pandas as pd
import yfinance as yf

from backend.backtester.models import BacktestResult, Strategy, Trade
from backend.technicals.engine import _macd, _rsi


def _fetch_history_bt(symbol: str, lookback_days: int) -> pd.DataFrame | None:
    period = "5y" if lookback_days > 730 else "2y" if lookback_days > 365 else "1y"
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period=period, interval="1d", auto_adjust=True)
        if hist is None or hist.empty:
            return None
        cutoff = hist.index[-1] - pd.Timedelta(days=lookback_days)
        return hist[hist.index >= cutoff]
    except Exception:
        return None


def _bollinger(close: pd.Series, period: int = 20, n_std: int = 2) -> tuple[pd.Series, pd.Series]:
    mid = close.rolling(period).mean()
    band = close.rolling(period).std()
    return mid + n_std * band, mid - n_std * band  # upper, lower


def _rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def _macd_series(close: pd.Series) -> tuple[pd.Series, pd.Series]:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal


def _strategy_rsi(close: pd.Series) -> list[Trade]:
    rsi = _rsi_series(close)
    trades: list[Trade] = []
    in_position = False
    buy_price = 0.0
    for i in range(1, len(close)):
        if pd.isna(rsi.iloc[i]) or pd.isna(rsi.iloc[i - 1]):
            continue
        idx_date = close.index[i]
        price = float(close.iloc[i])
        d = idx_date.date() if hasattr(idx_date, "date") else date.fromisoformat(str(idx_date)[:10])
        if not in_position and rsi.iloc[i - 1] >= 30 > rsi.iloc[i]:
            trades.append(Trade(date=d, action="buy", price=Decimal(str(round(price, 4)))))
            buy_price = price
            in_position = True
        elif in_position and rsi.iloc[i - 1] <= 70 < rsi.iloc[i]:
            pnl = Decimal(str(round((price / buy_price - 1) * 100, 4)))
            trades.append(Trade(date=d, action="sell", price=Decimal(str(round(price, 4))), pnl_pct=pnl))
            in_position = False
    return trades


def _strategy_macd_cross(close: pd.Series) -> list[Trade]:
    macd, signal = _macd_series(close)
    trades: list[Trade] = []
    in_position = False
    buy_price = 0.0
    for i in range(1, len(close)):
        if any(pd.isna(v) for v in [macd.iloc[i], macd.iloc[i - 1], signal.iloc[i], signal.iloc[i - 1]]):
            continue
        idx_date = close.index[i]
        price = float(close.iloc[i])
        d = idx_date.date() if hasattr(idx_date, "date") else date.fromisoformat(str(idx_date)[:10])
        crossed_above = macd.iloc[i - 1] < signal.iloc[i - 1] and macd.iloc[i] >= signal.iloc[i]
        crossed_below = macd.iloc[i - 1] > signal.iloc[i - 1] and macd.iloc[i] <= signal.iloc[i]
        if not in_position and crossed_above:
            trades.append(Trade(date=d, action="buy", price=Decimal(str(round(price, 4)))))
            buy_price = price
            in_position = True
        elif in_position and crossed_below:
            pnl = Decimal(str(round((price / buy_price - 1) * 100, 4)))
            trades.append(Trade(date=d, action="sell", price=Decimal(str(round(price, 4))), pnl_pct=pnl))
            in_position = False
    return trades


def _strategy_sma_cross(close: pd.Series) -> list[Trade]:
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    trades: list[Trade] = []
    in_position = False
    buy_price = 0.0
    for i in range(1, len(close)):
        if any(pd.isna(v) for v in [sma50.iloc[i], sma50.iloc[i - 1], sma200.iloc[i], sma200.iloc[i - 1]]):
            continue
        idx_date = close.index[i]
        price = float(close.iloc[i])
        d = idx_date.date() if hasattr(idx_date, "date") else date.fromisoformat(str(idx_date)[:10])
        golden = sma50.iloc[i - 1] < sma200.iloc[i - 1] and sma50.iloc[i] >= sma200.iloc[i]
        death = sma50.iloc[i - 1] > sma200.iloc[i - 1] and sma50.iloc[i] <= sma200.iloc[i]
        if not in_position and golden:
            trades.append(Trade(date=d, action="buy", price=Decimal(str(round(price, 4)))))
            buy_price = price
            in_position = True
        elif in_position and death:
            pnl = Decimal(str(round((price / buy_price - 1) * 100, 4)))
            trades.append(Trade(date=d, action="sell", price=Decimal(str(round(price, 4))), pnl_pct=pnl))
            in_position = False
    return trades


def _strategy_bb_reversion(close: pd.Series) -> list[Trade]:
    upper, lower = _bollinger(close)
    trades: list[Trade] = []
    in_position = False
    buy_price = 0.0
    for i in range(1, len(close)):
        if any(pd.isna(v) for v in [upper.iloc[i], lower.iloc[i]]):
            continue
        idx_date = close.index[i]
        price = float(close.iloc[i])
        d = idx_date.date() if hasattr(idx_date, "date") else date.fromisoformat(str(idx_date)[:10])
        if not in_position and price < float(lower.iloc[i]):
            trades.append(Trade(date=d, action="buy", price=Decimal(str(round(price, 4)))))
            buy_price = price
            in_position = True
        elif in_position and price > float(upper.iloc[i]):
            pnl = Decimal(str(round((price / buy_price - 1) * 100, 4)))
            trades.append(Trade(date=d, action="sell", price=Decimal(str(round(price, 4))), pnl_pct=pnl))
            in_position = False
    return trades


def _run_strategy(close: pd.Series, strategy: Strategy) -> list[Trade]:
    if strategy == "rsi":
        return _strategy_rsi(close)
    if strategy == "macd_cross":
        return _strategy_macd_cross(close)
    if strategy == "sma_cross":
        return _strategy_sma_cross(close)
    return _strategy_bb_reversion(close)


def _compute_metrics(
    trades: list[Trade],
    close: pd.Series,
    lookback_days: int,
) -> dict:
    closed = [t for t in trades if t.action == "sell" and t.pnl_pct is not None]
    total_trades = len(closed)

    # Compound return across all closed trades
    compound = 1.0
    for t in closed:
        compound *= 1 + float(t.pnl_pct) / 100
    total_return = (compound - 1) * 100

    # CAGR
    years = lookback_days / 365
    cagr = ((compound ** (1 / years)) - 1) * 100 if years > 0 and compound > 0 else 0.0

    # Sharpe — on daily close returns over the full window
    daily = close.pct_change().dropna()
    rf_daily = 0.05 / 252
    excess = daily - rf_daily
    sharpe = None
    if len(excess) > 1 and float(excess.std()) > 0:
        sharpe = round(float(excess.mean()) / float(excess.std()) * math.sqrt(252), 4)

    # Max drawdown on equity curve
    equity = [1.0]
    for t in closed:
        equity.append(equity[-1] * (1 + float(t.pnl_pct) / 100))
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100
        if dd > max_dd:
            max_dd = dd

    win_rate = (len([t for t in closed if t.pnl_pct and t.pnl_pct > 0]) / total_trades * 100) if total_trades else 0.0

    return {
        "total_return_pct": Decimal(str(round(total_return, 4))),
        "cagr_pct": Decimal(str(round(cagr, 4))),
        "sharpe_ratio": Decimal(str(sharpe)) if sharpe is not None else None,
        "max_drawdown_pct": Decimal(str(round(max_dd, 4))),
        "win_rate_pct": Decimal(str(round(win_rate, 4))),
        "total_trades": total_trades,
    }


async def run_backtest(
    ticker: str,
    strategy: Strategy,
    lookback_days: int = 365,
) -> BacktestResult:
    hist = await asyncio.to_thread(_fetch_history_bt, ticker.upper(), lookback_days)
    if hist is None or len(hist) < 40:
        raise ValueError(f"Insufficient history for {ticker}")
    close = hist["Close"]
    trades = _run_strategy(close, strategy)
    metrics = _compute_metrics(trades, close, lookback_days)
    return BacktestResult(
        ticker=ticker.upper(),
        strategy=strategy,
        lookback_days=lookback_days,
        trades=trades,
        **metrics,
    )
