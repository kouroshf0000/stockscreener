from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from backend.data_providers.models import FinancialStatement, Fundamentals
from backend.valuation import derivation as deriv
from backend.valuation.derivation import (
    EXPLICIT_YEARS,
    HIGH_GROWTH_YEARS,
    _ebit_margin,
    _effective_tax,
    _margin_path,
    _reinvestment_rate_from_components,
    _revenue_cagr,
    _two_stage_growth,
    derive_assumptions,
)


def _stmt(period: str, **kw: Decimal | None) -> FinancialStatement:
    return FinancialStatement(period_end=date.fromisoformat(period), **kw)


def _f() -> Fundamentals:
    return Fundamentals(
        ticker="X",
        sector="Technology",
        market_cap=Decimal("100_000"),
        beta=Decimal("1.2"),
        price=Decimal("100"),
        statements=[
            _stmt(
                "2025-12-31",
                revenue=Decimal("1000"),
                operating_income=Decimal("250"),
                free_cash_flow=Decimal("180"),
                capex=Decimal("-70"),
                working_capital_change=Decimal("-20"),
                stock_based_compensation=Decimal("40"),
                tax_rate=Decimal("0.22"),
                total_debt=Decimal("100"),
                cash_and_equivalents=Decimal("200"),
                shares_outstanding=Decimal("10"),
            ),
            _stmt("2024-12-31", revenue=Decimal("850"), operating_income=Decimal("200"), tax_rate=Decimal("0.20"), capex=Decimal("-60"), stock_based_compensation=Decimal("35"), free_cash_flow=Decimal("150")),
            _stmt("2023-12-31", revenue=Decimal("720"), operating_income=Decimal("170"), tax_rate=Decimal("0.19"), capex=Decimal("-55"), stock_based_compensation=Decimal("30"), free_cash_flow=Decimal("120")),
            _stmt("2022-12-31", revenue=Decimal("600"), operating_income=Decimal("130"), tax_rate=Decimal("0.18"), capex=Decimal("-45"), stock_based_compensation=Decimal("25"), free_cash_flow=Decimal("90")),
        ],
        as_of=date(2026, 4, 17),
    )


def test_revenue_cagr_matches_hand_calc() -> None:
    f = _f()
    cagr = _revenue_cagr(f.statements, years=3)
    assert cagr is not None
    expected = (1000 / 600) ** (1 / 3) - 1
    assert abs(float(cagr) - expected) < 1e-4


def test_two_stage_growth_structure() -> None:
    path = _two_stage_growth(Decimal("0.20"), Decimal("0.03"))
    assert len(path) == EXPLICIT_YEARS
    assert all(p == Decimal("0.20") for p in path[:HIGH_GROWTH_YEARS])
    assert path[-1] == Decimal("0.03")


def test_margin_path_fades_monotone() -> None:
    path = _margin_path(Decimal("0.30"), Decimal("0.15"), years=EXPLICIT_YEARS)
    assert len(path) == EXPLICIT_YEARS
    assert path[0] > path[-1]
    assert path[-1] == Decimal("0.15")


def test_effective_tax_bounded() -> None:
    f = _f()
    t = _effective_tax(f.statements)
    assert t is not None
    assert Decimal("0.10") <= t <= Decimal("0.35")


def test_ebit_margin_bounded() -> None:
    f = _f()
    m = _ebit_margin(f.statements)
    assert m is not None
    assert Decimal("0.02") <= m <= Decimal("0.55")


def test_reinvestment_includes_nwc_and_sbc() -> None:
    from backend.valuation.sector_profiles import get_profile
    f = _f()
    profile = get_profile("Technology")
    r = _reinvestment_rate_from_components(f.statements, Decimal("0.25"), profile)
    assert r is not None
    assert Decimal("0.05") <= r <= Decimal("0.95")


@pytest.mark.asyncio
async def test_derive_assumptions_uses_filings_not_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _rf() -> object:
        from backend.data_providers.models import RiskFreeRate

        return RiskFreeRate(rate=Decimal("0.04"), as_of=date(2026, 4, 17), series_id="DGS10")

    async def _gdp() -> Decimal:
        return Decimal("0.04")

    async def _ey() -> Decimal:
        return Decimal("0.07")

    monkeypatch.setattr(deriv, "fetch_risk_free_rate", _rf)
    monkeypatch.setattr(deriv, "_long_run_nominal_gdp", _gdp)
    monkeypatch.setattr(deriv, "_spx_earnings_yield", _ey)

    d = await derive_assumptions(_f(), peer_ev_ebitda=Decimal("15"))
    a = d.assumptions
    assert len(a.revenue_growth) == EXPLICIT_YEARS
    assert a.ebit_margin_path is not None
    assert a.exit_multiple_ev_ebitda == Decimal("15")
    assert a.terminal_growth == Decimal("0.04")
    assert a.equity_risk_premium == Decimal("0.04")  # clamped to Damodaran floor [0.04, 0.065]
    assert "2-stage" in d.provenance["revenue_growth"]
