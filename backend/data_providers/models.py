from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class FinancialStatement(BaseModel):
    model_config = ConfigDict(frozen=True)

    period_end: date
    revenue: Decimal | None = None
    operating_income: Decimal | None = None
    net_income: Decimal | None = None
    ebitda: Decimal | None = None
    free_cash_flow: Decimal | None = None
    operating_cash_flow: Decimal | None = None
    capex: Decimal | None = None
    depreciation_and_amortization: Decimal | None = None
    working_capital_change: Decimal | None = None
    stock_based_compensation: Decimal | None = None
    total_debt: Decimal | None = None
    operating_lease_liability: Decimal | None = None
    cash_and_equivalents: Decimal | None = None
    total_equity: Decimal | None = None
    shares_outstanding: Decimal | None = None
    interest_expense: Decimal | None = None
    tax_rate: Decimal | None = None


class Fundamentals(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    market_cap: Decimal | None = None
    beta: Decimal | None = None
    price: Decimal | None = None
    currency: str = "USD"
    statements: list[FinancialStatement] = Field(default_factory=list)
    as_of: date


class Quote(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    price: Decimal
    volume: int
    as_of: date


class RiskFreeRate(BaseModel):
    model_config = ConfigDict(frozen=True)

    rate: Decimal
    as_of: date
    series_id: str = "DGS10"


class FilingRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    cik: str
    accession: str
    form: str
    filed: date
    primary_doc_url: str
