from __future__ import annotations

from decimal import Decimal

from backend.data_providers.models import Fundamentals
from backend.valuation.models import WACCBreakdown, WACCInputs

DEFAULT_COST_OF_DEBT = Decimal("0.055")


def estimate_cost_of_debt(f: Fundamentals) -> Decimal:
    if not f.statements:
        return DEFAULT_COST_OF_DEBT
    s = f.statements[0]
    if s.interest_expense is None or s.total_debt is None or s.total_debt <= 0:
        return DEFAULT_COST_OF_DEBT
    rate = abs(s.interest_expense) / s.total_debt
    rate = max(Decimal("0.01"), min(rate, Decimal("0.15")))
    return rate


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
