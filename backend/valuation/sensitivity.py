from __future__ import annotations

from decimal import Decimal

from backend.data_providers.models import Fundamentals
from backend.valuation.dcf import run_dcf
from backend.valuation.models import Assumptions, SensitivityCell, SensitivityTable


def _range(lo: Decimal, hi: Decimal, step: Decimal) -> list[Decimal]:
    out: list[Decimal] = []
    v = lo
    while v <= hi + Decimal("0.000001"):
        out.append(v)
        v += step
    return out


def sensitivity_table(
    f: Fundamentals,
    base: Assumptions,
    risk_free_rate: Decimal,
    wacc_lo: Decimal = Decimal("0.07"),
    wacc_hi: Decimal = Decimal("0.11"),
    wacc_step: Decimal = Decimal("0.005"),
    growth_lo: Decimal = Decimal("0.01"),
    growth_hi: Decimal = Decimal("0.03"),
    growth_step: Decimal = Decimal("0.005"),
) -> SensitivityTable:
    wacc_axis = _range(wacc_lo, wacc_hi, wacc_step)
    growth_axis = _range(growth_lo, growth_hi, growth_step)

    cells: list[SensitivityCell] = []
    for w in wacc_axis:
        implied_erp = w - risk_free_rate
        beta = f.beta or Decimal(1)
        adj_erp = implied_erp / beta if beta > 0 else implied_erp
        for g in growth_axis:
            if w <= g:
                continue
            a = Assumptions(
                revenue_growth=base.revenue_growth,
                ebit_margin=base.ebit_margin,
                tax_rate=base.tax_rate,
                reinvestment_rate=base.reinvestment_rate,
                terminal_growth=g,
                equity_risk_premium=adj_erp,
            )
            try:
                r = run_dcf(f, risk_free_rate=risk_free_rate, assumptions=a)
            except Exception:
                continue
            cells.append(
                SensitivityCell(wacc=w, terminal_growth=g, implied_price=r.implied_share_price)
            )
    return SensitivityTable(wacc_axis=wacc_axis, growth_axis=growth_axis, cells=cells)
