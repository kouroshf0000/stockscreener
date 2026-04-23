from __future__ import annotations

from decimal import Decimal

from backend.data_providers.models import Fundamentals
from backend.valuation.models import WACCBreakdown, WACCInputs

DEFAULT_COST_OF_DEBT = Decimal("0.055")
_D_E_HY_THRESHOLD = Decimal("2.0")  # D/E above this → use HY spread proxy


def estimate_cost_of_debt(f: Fundamentals) -> Decimal:
    # 1. Actual interest rate from financials (most accurate)
    if f.statements:
        s = f.statements[0]
        if s.interest_expense is not None and s.total_debt is not None and s.total_debt > 0:
            actual = abs(s.interest_expense) / s.total_debt
            actual = max(Decimal("0.01"), min(actual, Decimal("0.15")))
            return actual

    # 2. Use FRED credit spread + risk-free rate as market-implied cost of debt.
    # High-leverage companies (D/E > 2) use HY spread; others use IG spread.
    rfr_approx = Decimal("0.045")  # fallback when live rate unavailable
    d_e = f.debt_to_equity
    if d_e is not None and d_e > _D_E_HY_THRESHOLD and f.credit_spread_hy is not None:
        return max(Decimal("0.04"), rfr_approx + f.credit_spread_hy)
    if f.credit_spread_ig is not None:
        return max(Decimal("0.03"), rfr_approx + f.credit_spread_ig)

    return DEFAULT_COST_OF_DEBT


def compute_wacc(inputs: WACCInputs) -> WACCBreakdown:
    re = inputs.risk_free_rate + inputs.beta * inputs.equity_risk_premium
    rd = inputs.cost_of_debt * (Decimal(1) - inputs.tax_rate)
    total = inputs.market_cap + inputs.total_debt
    if total <= 0:
        return WACCBreakdown(
            cost_of_equity=re,
            cost_of_debt_after_tax=rd,
            weight_equity=Decimal(1),
            weight_debt=Decimal(0),
            wacc=re,
        )
    we = inputs.market_cap / total
    wd = inputs.total_debt / total
    wacc = we * re + wd * rd
    return WACCBreakdown(
        cost_of_equity=re,
        cost_of_debt_after_tax=rd,
        weight_equity=we,
        weight_debt=wd,
        wacc=wacc,
    )
