from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from backend.data_providers.models import FilingRef, FinancialStatement, Fundamentals
from backend.filings import data_audit
from backend.filings.risk_factors import RiskExtractionTrace


def _fundamentals() -> Fundamentals:
    return Fundamentals(
        ticker="AAPL",
        name="Apple Inc.",
        statements=[
            FinancialStatement(
                period_end=date(2025, 9, 27),
                revenue=Decimal("1000"),
                total_debt=Decimal("200"),
                shares_outstanding=Decimal("50"),
            )
        ],
        as_of=date(2026, 4, 17),
    )


@pytest.mark.asyncio
async def test_audit_data_quality_flags_mismatches(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_fundamentals(_ticker: str) -> Fundamentals:
        return _fundamentals()

    async def _fake_trace(_ticker: str, include_quarterly: bool = False) -> RiskExtractionTrace:
        filing = FilingRef(
            cik="0000320193",
            accession="0000320193-26-000001",
            form="10-K",
            filed=date(2026, 1, 31),
            primary_doc_url="https://example.com/10k.htm",
        )
        text = """
        Total net sales $1,020
        Long-term debt $180
        Current portion of long-term debt $40
        53 shares outstanding
        """
        return RiskExtractionTrace(text=text, reason="ok", filing=filing, doc_url=filing.primary_doc_url, chars=len(text), attempts=[])

    monkeypatch.setattr(data_audit, "fetch_fundamentals", _fake_fundamentals)
    monkeypatch.setattr(data_audit, "fetch_risk_factors_universal", _fake_trace)

    report = await data_audit.audit_data_quality("AAPL")
    assert report.ticker == "AAPL"
    assert report.overall == "unreliable"
    checks = {check.field: check for check in report.checks}
    assert checks["revenue"].status == "needs_review"
    assert checks["total_debt"].status == "critical_mismatch"
    assert checks["shares_outstanding"].status == "critical_mismatch"


def test_report_from_values_handles_missing_matches() -> None:
    report = data_audit._report_from_values(
        ticker="MSFT",
        as_of=date(2026, 4, 17),
        revenue_yf=Decimal("100"),
        debt_yf=Decimal("20"),
        shares_yf=Decimal("10"),
        cleaned_filing_text="no gaap line items here",
    )
    assert report.overall == "degraded"
    assert all(check.status == "needs_review" for check in report.checks)
