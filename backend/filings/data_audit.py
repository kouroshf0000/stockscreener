from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.data_providers.yfinance_client import fetch_fundamentals
from backend.filings.extractor import clean_text
from backend.filings.risk_factors import fetch_risk_factors_universal


AuditStatus = Literal["ok", "needs_review", "critical_mismatch"]
OverallStatus = Literal["ok", "degraded", "unreliable"]

_AMOUNT_PATTERNS = {
    "revenue": re.compile(
        r"(?:total\s+net\s+sales|total\s+revenues?|net\s+revenues?)"
        r"[^$\d]{0,80}\$?\s*\(?\s*([\d,]+(?:\.\d+)?)\s*\)?",
        re.IGNORECASE,
    ),
    "long_term_debt": re.compile(
        r"long[- ]term\s+debt[^$\d]{0,80}\$?\s*\(?\s*([\d,]+(?:\.\d+)?)\s*\)?",
        re.IGNORECASE,
    ),
    "current_debt": re.compile(
        r"current\s+portion\s+of\s+long[- ]term\s+debt[^$\d]{0,80}\$?\s*\(?\s*([\d,]+(?:\.\d+)?)\s*\)?",
        re.IGNORECASE,
    ),
    "shares_outstanding": re.compile(
        r"([\d,]+(?:\.\d+)?)\s+(?:shares|share)\s+outstanding",
        re.IGNORECASE,
    ),
}


class QualityCheck(BaseModel):
    model_config = ConfigDict(frozen=True)
    field: str
    yfinance_value: Decimal | None
    filing_value: Decimal | None
    delta_pct: Decimal | None
    status: AuditStatus


class DataQualityReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    ticker: str
    as_of: date
    checks: list[QualityCheck]
    overall: OverallStatus


def _parse_decimal(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    try:
        return Decimal(raw.replace(",", ""))
    except Exception:
        return None


def _extract_amount(pattern: re.Pattern[str], text: str) -> Decimal | None:
    match = pattern.search(text)
    if not match:
        return None
    return _parse_decimal(match.group(1))


def _extract_total_debt(text: str) -> Decimal | None:
    long_term = _extract_amount(_AMOUNT_PATTERNS["long_term_debt"], text)
    current = _extract_amount(_AMOUNT_PATTERNS["current_debt"], text)
    if long_term is None and current is None:
        return None
    return (long_term or Decimal(0)) + (current or Decimal(0))


def _delta_pct(yfinance_value: Decimal | None, filing_value: Decimal | None) -> Decimal | None:
    if yfinance_value in (None, Decimal(0)) or filing_value is None:
        return None
    return (filing_value - yfinance_value) / yfinance_value


def _status_for(delta_pct: Decimal | None, yfinance_value: Decimal | None, filing_value: Decimal | None) -> AuditStatus:
    if yfinance_value is None or filing_value is None or delta_pct is None:
        return "needs_review"
    abs_delta = abs(delta_pct)
    if abs_delta > Decimal("0.05"):
        return "critical_mismatch"
    if abs_delta > Decimal("0.01"):
        return "needs_review"
    return "ok"


def _overall(checks: list[QualityCheck]) -> OverallStatus:
    if any(check.status == "critical_mismatch" for check in checks):
        return "unreliable"
    if any(check.status == "needs_review" for check in checks):
        return "degraded"
    return "ok"


def _report_from_values(
    ticker: str,
    as_of: date,
    revenue_yf: Decimal | None,
    debt_yf: Decimal | None,
    shares_yf: Decimal | None,
    cleaned_filing_text: str,
) -> DataQualityReport:
    revenue_filing = _extract_amount(_AMOUNT_PATTERNS["revenue"], cleaned_filing_text)
    debt_filing = _extract_total_debt(cleaned_filing_text)
    shares_filing = _extract_amount(_AMOUNT_PATTERNS["shares_outstanding"], cleaned_filing_text)

    checks = [
        QualityCheck(
            field="revenue",
            yfinance_value=revenue_yf,
            filing_value=revenue_filing,
            delta_pct=_delta_pct(revenue_yf, revenue_filing),
            status=_status_for(_delta_pct(revenue_yf, revenue_filing), revenue_yf, revenue_filing),
        ),
        QualityCheck(
            field="total_debt",
            yfinance_value=debt_yf,
            filing_value=debt_filing,
            delta_pct=_delta_pct(debt_yf, debt_filing),
            status=_status_for(_delta_pct(debt_yf, debt_filing), debt_yf, debt_filing),
        ),
        QualityCheck(
            field="shares_outstanding",
            yfinance_value=shares_yf,
            filing_value=shares_filing,
            delta_pct=_delta_pct(shares_yf, shares_filing),
            status=_status_for(_delta_pct(shares_yf, shares_filing), shares_yf, shares_filing),
        ),
    ]
    return DataQualityReport(ticker=ticker.upper(), as_of=as_of, checks=checks, overall=_overall(checks))


async def audit_data_quality(ticker: str) -> DataQualityReport:
    fundamentals = await fetch_fundamentals(ticker)
    latest = fundamentals.statements[0] if fundamentals.statements else None
    trace = await fetch_risk_factors_universal(ticker)
    cleaned = clean_text(trace.text or "")
    return _report_from_values(
        ticker=ticker,
        as_of=fundamentals.as_of,
        revenue_yf=latest.revenue if latest else None,
        debt_yf=latest.total_debt if latest else None,
        shares_yf=latest.shares_outstanding if latest else None,
        cleaned_filing_text=cleaned,
    )
