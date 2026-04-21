from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from backend.data_providers.models import FinancialStatement, Fundamentals
from backend.valuation.auditor import audit, auditor_passes
from backend.valuation.dcf import run_dcf
from backend.valuation.models import Assumptions
from backend.valuation.monte_carlo import run_monte_carlo
from backend.valuation.sensitivity import sensitivity_table
from backend.valuation.wacc import WACCInputs, compute_wacc, estimate_cost_of_debt


def _stmt(
    period: str,
    revenue: Decimal | None = None,
    net_income: Decimal | None = None,
    ebitda: Decimal | None = None,
    fcf: Decimal | None = None,
    ocf: Decimal | None = None,
    capex: Decimal | None = None,
    total_debt: Decimal | None = None,
    cash: Decimal | None = None,
    equity: Decimal | None = None,
    shares: Decimal | None = None,
    interest: Decimal | None = None,
    tax_rate: Decimal | None = None,
    op_income: Decimal | None = None,
) -> FinancialStatement:
    return FinancialStatement(
        period_end=date.fromisoformat(period),
        revenue=revenue,
        operating_income=op_income,
        net_income=net_income,
        ebitda=ebitda,
        free_cash_flow=fcf,
        operating_cash_flow=ocf,
        capex=capex,
        total_debt=total_debt,
        cash_and_equivalents=cash,
        total_equity=equity,
        shares_outstanding=shares,
        interest_expense=interest,
        tax_rate=tax_rate,
    )


def _fund() -> Fundamentals:
    return Fundamentals(
        ticker="TEST",
        sector="Technology",
        market_cap=Decimal("10000"),
        beta=Decimal("1.2"),
        price=Decimal("100"),
        statements=[
            _stmt(
                "2025-12-31",
                revenue=Decimal("1000"),
                net_income=Decimal("150"),
                ebitda=Decimal("300"),
                fcf=Decimal("180"),
                ocf=Decimal("250"),
                capex=Decimal("-70"),
                total_debt=Decimal("2000"),
                cash=Decimal("500"),
                equity=Decimal("3000"),
                shares=Decimal("100"),
                interest=Decimal("100"),
                tax_rate=Decimal("0.21"),
                op_income=Decimal("200"),
            ),
            _stmt("2024-12-31", revenue=Decimal("900"), fcf=Decimal("150")),
            _stmt("2023-12-31", revenue=Decimal("800"), fcf=Decimal("120")),
            _stmt("2022-12-31", revenue=Decimal("700"), fcf=Decimal("100")),
        ],
        as_of=date(2026, 4, 17),
    )


def test_wacc_basic() -> None:
    wb = compute_wacc(
        WACCInputs(
            risk_free_rate=Decimal("0.04"),
            beta=Decimal("1.0"),
            equity_risk_premium=Decimal("0.055"),
            cost_of_debt=Decimal("0.05"),
            tax_rate=Decimal("0.21"),
            market_cap=Decimal("900"),
            total_debt=Decimal("100"),
        )
    )
    assert wb.cost_of_equity == Decimal("0.095")
    assert wb.weight_equity == Decimal("0.9")
    assert wb.weight_debt == Decimal("0.1")
    expected = Decimal("0.9") * Decimal("0.095") + Decimal("0.1") * Decimal("0.05") * (
        Decimal(1) - Decimal("0.21")
    )
    assert wb.wacc == expected


def test_estimate_cost_of_debt_bounds() -> None:
    f = _fund()
    cod = estimate_cost_of_debt(f)
    assert Decimal("0.01") <= cod <= Decimal("0.15")
    assert cod == Decimal("100") / Decimal("2000")


def test_dcf_produces_positive_price_and_five_years() -> None:
    f = _fund()
    a = Assumptions(
        revenue_growth=[Decimal("0.1")] * 5,
        ebit_margin=Decimal("0.2"),
        tax_rate=Decimal("0.21"),
        reinvestment_rate=Decimal("0.3"),
        terminal_growth=Decimal("0.025"),
    )
    r = run_dcf(f, risk_free_rate=Decimal("0.04"), assumptions=a)
    assert len(r.projections) == 5
    assert r.implied_share_price > 0
    assert r.enterprise_value > 0
    assert r.wacc.wacc > r.assumptions.terminal_growth
    assert r.upside_pct is not None


def test_dcf_rejects_wacc_below_terminal() -> None:
    f = _fund()
    a = Assumptions(terminal_growth=Decimal("0.5"))
    with pytest.raises(ValueError):
        run_dcf(f, risk_free_rate=Decimal("0.04"), assumptions=a)


def test_red_flag_fcf_outpaces_revenue() -> None:
    f = Fundamentals(
        ticker="RF",
        market_cap=Decimal("10000"),
        beta=Decimal("1.0"),
        price=Decimal("50"),
        statements=[
            _stmt("2025-12-31", revenue=Decimal("1100"), fcf=Decimal("300"),
                  total_debt=Decimal("100"), cash=Decimal("50"),
                  equity=Decimal("1000"), shares=Decimal("100"),
                  op_income=Decimal("220"), tax_rate=Decimal("0.21")),
            _stmt("2024-12-31", revenue=Decimal("1050"), fcf=Decimal("200")),
            _stmt("2023-12-31", revenue=Decimal("1000"), fcf=Decimal("120")),
            _stmt("2022-12-31", revenue=Decimal("950"), fcf=Decimal("70")),
        ],
        as_of=date(2026, 4, 17),
    )
    r = run_dcf(f, risk_free_rate=Decimal("0.04"))
    assert any("FCF growth outpaced" in x for x in r.red_flags)


def test_sensitivity_grid_shape() -> None:
    f = _fund()
    a = Assumptions()
    t = sensitivity_table(f, base=a, risk_free_rate=Decimal("0.04"))
    assert len(t.wacc_axis) == 9
    assert len(t.growth_axis) == 5
    assert len(t.cells) > 0
    assert all(c.implied_price > 0 for c in t.cells)


def test_monte_carlo_reasonable() -> None:
    f = _fund()
    a = Assumptions()
    mc = run_monte_carlo(f, base=a, risk_free_rate=Decimal("0.04"), iterations=200)
    assert mc.iterations > 0
    assert mc.p10 <= mc.p50 <= mc.p90


def test_auditor_detects_missing_debt() -> None:
    f = Fundamentals(
        ticker="BAD",
        market_cap=Decimal("10000"),
        statements=[
            _stmt("2025-12-31", revenue=Decimal("100"), shares=Decimal("10")),
            _stmt("2024-12-31", revenue=Decimal("90"), shares=Decimal("10")),
        ],
        as_of=date(2026, 4, 17),
    )
    findings = audit(f)
    debt_rule = next(x for x in findings if x.rule == "debt")
    assert "WARN" in debt_rule.detail  # missing debt is a warning, not a block
