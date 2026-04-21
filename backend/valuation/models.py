from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class Assumptions(BaseModel):
    model_config = ConfigDict(frozen=True)
    revenue_growth: list[Decimal] = Field(
        default_factory=lambda: [Decimal("0.08")] * 5,
        description="Explicit revenue growth per forecast year (IB models: 5-10Y).",
    )
    ebit_margin: Decimal = Decimal("0.20")
    ebit_margin_path: list[Decimal] | None = Field(
        default=None,
        description="Optional per-year EBIT margin (overrides flat ebit_margin).",
    )
    tax_rate: Decimal = Decimal("0.21")
    reinvestment_rate: Decimal = Decimal("0.30")
    reinvestment_rate_path: list[Decimal] | None = Field(default=None)
    terminal_growth: Decimal = Decimal("0.025")
    equity_risk_premium: Decimal = Decimal("0.055")
    risk_premium_adjustment: Decimal = Decimal("0")
    exit_multiple_ev_ebitda: Decimal | None = Field(
        default=None,
        description="If set, terminal value = min(Gordon, exit_multiple * terminal_EBITDA).",
    )


class WACCInputs(BaseModel):
    model_config = ConfigDict(frozen=True)
    risk_free_rate: Decimal
    beta: Decimal
    equity_risk_premium: Decimal
    cost_of_debt: Decimal
    tax_rate: Decimal
    market_cap: Decimal
    total_debt: Decimal


class WACCBreakdown(BaseModel):
    model_config = ConfigDict(frozen=True)
    cost_of_equity: Decimal
    cost_of_debt_after_tax: Decimal
    weight_equity: Decimal
    weight_debt: Decimal
    wacc: Decimal


class ProjectionRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    year: int
    revenue: Decimal
    ebit: Decimal
    nopat: Decimal
    reinvestment: Decimal
    fcff: Decimal
    discount_factor: Decimal
    pv_fcff: Decimal


class DCFResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    ticker: str
    as_of: date
    wacc: WACCBreakdown
    assumptions: Assumptions
    projections: list[ProjectionRow]
    pv_explicit: Decimal
    terminal_value: Decimal
    pv_terminal: Decimal
    enterprise_value: Decimal
    net_debt: Decimal
    equity_value: Decimal
    shares_outstanding: Decimal
    implied_share_price: Decimal
    current_price: Decimal | None
    upside_pct: Decimal | None
    red_flags: list[str] = []


class SensitivityCell(BaseModel):
    model_config = ConfigDict(frozen=True)
    wacc: Decimal
    terminal_growth: Decimal
    implied_price: Decimal


class SensitivityTable(BaseModel):
    model_config = ConfigDict(frozen=True)
    wacc_axis: list[Decimal]
    growth_axis: list[Decimal]
    cells: list[SensitivityCell]


class AuditFinding(BaseModel):
    model_config = ConfigDict(frozen=True)
    rule: str
    ok: bool
    detail: str
