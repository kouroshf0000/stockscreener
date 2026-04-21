from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from backend.comps import engine as comps_engine
from backend.comps.peer_map import peers_for
from backend.data_providers.models import FinancialStatement, Fundamentals


def _mk(
    sym: str, mcap: int, ni: int, ebitda: int, debt: int = 0, cash: int = 0, shares: int = 100
) -> Fundamentals:
    return Fundamentals(
        ticker=sym,
        sector="Technology",
        market_cap=Decimal(mcap),
        price=Decimal("100"),
        statements=[
            FinancialStatement(
                period_end=date(2025, 12, 31),
                net_income=Decimal(ni),
                ebitda=Decimal(ebitda),
                total_debt=Decimal(debt),
                cash_and_equivalents=Decimal(cash),
                shares_outstanding=Decimal(shares),
            )
        ],
        as_of=date(2026, 4, 17),
    )


def test_peer_map_override() -> None:
    assert "AMD" in peers_for("NVDA")
    assert peers_for("UNKNOWN") == []
    assert peers_for("UNKNOWN", fallback_sector_peers=["X", "Y", "Z"]) == ["X", "Y", "Z"]


@pytest.mark.asyncio
async def test_run_comps_weights_and_medians(monkeypatch: pytest.MonkeyPatch) -> None:
    target = _mk("NVDA", 3000, 300, 600, debt=100, cash=50, shares=100)
    fake = {
        "NVDA": target,
        "AMD": _mk("AMD", 1000, 50, 100),
        "INTC": _mk("INTC", 2000, 200, 400),
        "AVGO": _mk("AVGO", 1500, 100, 250),
    }

    async def _fetch(sym: str) -> Fundamentals:
        return fake[sym]

    monkeypatch.setattr(comps_engine, "fetch_fundamentals", _fetch)
    monkeypatch.setattr(comps_engine, "peers_for", lambda _t: ["AMD", "INTC", "AVGO"])

    res = await comps_engine.run_comps("NVDA")
    assert res.target == "NVDA"
    assert len(res.peers) == 3
    assert res.weighted_pe is not None
    assert res.median_pe is not None
    assert res.implied_price_pe is not None
    assert res.implied_price_pe > 0
    assert res.implied_price_ev_ebitda is not None
    assert res.implied_price_ev_ebitda > 0
