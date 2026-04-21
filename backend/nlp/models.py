from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RiskLevel = Literal[0, 1, 2, 3]


class RiskAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)
    legal_risk: RiskLevel = Field(description="0=none, 3=severe unresolved litigation")
    regulatory_risk: RiskLevel
    macro_risk: RiskLevel
    competitive_risk: RiskLevel
    summary: str
    top_risks: list[str] = Field(default_factory=list, max_length=5)


class RiskOutput(BaseModel):
    model_config = ConfigDict(frozen=True)
    ticker: str
    assessment: RiskAssessment
    discount_rate_adjustment: Decimal
    source: Literal["haiku", "fallback"] = "haiku"
    fallback_reason: str | None = None
    filing_accession: str | None = None
    filing_form: str | None = None
    filing_date: str | None = None
    filing_url: str | None = None
    risk_factors_chars: int | None = None
