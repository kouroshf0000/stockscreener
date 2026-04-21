from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from backend.data_providers import yfinance_client
from backend.data_providers.models import Fundamentals


class _FakeTicker:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        col = pd.Timestamp("2025-12-31")
        self.income_stmt = pd.DataFrame(
            {
                col: {
                    "Total Revenue": 100_000,
                    "Operating Income": 30_000,
                    "Net Income": 25_000,
                    "Interest Expense": 2_000,
                    "Tax Provision": 5_000,
                    "Pretax Income": 30_000,
                    "Reconciled Depreciation": 5_000,
                }
            }
        )
        self.cashflow = pd.DataFrame(
            {
                col: {
                    "Operating Cash Flow": 35_000,
                    "Capital Expenditure": -10_000,
                    "Free Cash Flow": 25_000,
                    "Depreciation And Amortization": 5_000,
                }
            }
        )
        self.balance_sheet = pd.DataFrame(
            {
                col: {
                    "Total Debt": 40_000,
                    "Cash And Cash Equivalents": 20_000,
                    "Stockholders Equity": 80_000,
                    "Ordinary Shares Number": 1_000,
                }
            }
        )
        self.info = {
            "shortName": "Fake Co",
            "sector": "Technology",
            "industry": "Semis",
            "marketCap": 500_000,
            "beta": 1.3,
            "currentPrice": 123.45,
            "currency": "USD",
        }

        class _Fast:
            last_price = 123.45
            last_volume = 1_234_567

        self.fast_info = _Fast()


@pytest.mark.asyncio
async def test_fetch_fundamentals_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(yfinance_client.yf, "Ticker", _FakeTicker)
    fund = await yfinance_client.fetch_fundamentals("fake")
    assert isinstance(fund, Fundamentals)
    assert fund.ticker == "FAKE"
    assert fund.sector == "Technology"
    assert fund.beta == Decimal("1.3")
    assert fund.price == Decimal("123.45")
    assert len(fund.statements) == 1
    s = fund.statements[0]
    assert s.revenue == Decimal("100000")
    assert s.ebitda == Decimal("35000")
    assert s.free_cash_flow == Decimal("25000")
    assert s.period_end == date(2025, 12, 31)
    assert s.tax_rate == Decimal("5000") / Decimal("30000")


@pytest.mark.asyncio
async def test_fundamentals_are_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def _factory(symbol: str) -> _FakeTicker:
        calls["n"] += 1
        return _FakeTicker(symbol)

    monkeypatch.setattr(yfinance_client.yf, "Ticker", _factory)
    a = await yfinance_client.fetch_fundamentals("fake")
    b = await yfinance_client.fetch_fundamentals("fake")
    assert a == b
    assert calls["n"] == 1
