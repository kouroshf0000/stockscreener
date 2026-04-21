from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from backend.data_providers.models import FinancialStatement, Fundamentals
from backend.screener import engine as engine_mod
from backend.screener.dsl import Filter, ScreenRequest
from backend.screener.etf_holdings import overlap_with


def _mk(
    sym: str, sector: str, mcap: int, ni: int, rev_now: int, rev_3y: int
) -> Fundamentals:
    return Fundamentals(
        ticker=sym,
        sector=sector,
        market_cap=Decimal(mcap),
        price=Decimal("100"),
        statements=[
            FinancialStatement(
                period_end=date(2025, 12, 31),
                revenue=Decimal(rev_now),
                net_income=Decimal(ni),
                ebitda=Decimal(ni * 2),
                free_cash_flow=Decimal(ni),
                total_debt=Decimal(0),
                cash_and_equivalents=Decimal(0),
                total_equity=Decimal(mcap // 2),
                operating_income=Decimal(ni),
                tax_rate=Decimal("0.21"),
            ),
            FinancialStatement(period_end=date(2024, 12, 31), revenue=Decimal(rev_now * 90 // 100)),
            FinancialStatement(period_end=date(2023, 12, 31), revenue=Decimal(rev_now * 80 // 100)),
            FinancialStatement(period_end=date(2022, 12, 31), revenue=Decimal(rev_3y)),
        ],
        as_of=date(2026, 4, 17),
    )


@pytest.mark.asyncio
async def test_run_screen_filters_and_sorts(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = {
        "A": _mk("A", "Tech", 2_000, 100, 2000, 1000),
        "B": _mk("B", "Tech", 1_000, 10, 2000, 1000),
        "C": _mk("C", "Tech", 3_000, 200, 2000, 1000),
    }

    async def _fetch(sym: str) -> Fundamentals:
        return fake[sym]

    monkeypatch.setattr(engine_mod, "fetch_fundamentals", _fetch)
    monkeypatch.setattr(engine_mod, "universe_for", lambda _n: tuple(fake.keys()))

    req = ScreenRequest(
        universe="SP500",
        filters=[Filter(metric="pe_ratio", op="lt", value=Decimal("50"))],
    )
    resp = await engine_mod.run_screen(req)
    assert [r.symbol for r in resp.rows] == ["C", "A"]
    assert resp.total == 2


@pytest.mark.asyncio
async def test_vs_sector_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = {
        "A": _mk("A", "Tech", 2_000, 100, 2000, 1000),
        "B": _mk("B", "Tech", 1_000, 10, 2000, 1000),
        "C": _mk("C", "Tech", 3_000, 200, 2000, 1000),
    }

    async def _fetch(sym: str) -> Fundamentals:
        return fake[sym]

    monkeypatch.setattr(engine_mod, "fetch_fundamentals", _fetch)
    monkeypatch.setattr(engine_mod, "universe_for", lambda _n: tuple(fake.keys()))

    req = ScreenRequest(
        universe="SP500",
        filters=[Filter(metric="pe_ratio", op="lt", value=Decimal("0.8"), vs_sector=True)],
    )
    resp = await engine_mod.run_screen(req)
    syms = [r.symbol for r in resp.rows]
    assert "C" in syms


def test_etf_overlap() -> None:
    assert "AAPL" in overlap_with(["AAPL", "FOO"], "SPY")
    assert overlap_with(["FOO"], "SPY") == []
