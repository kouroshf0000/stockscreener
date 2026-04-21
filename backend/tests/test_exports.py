from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from backend.comps.engine import CompsResult, PeerRow
from backend.data_providers.models import FinancialStatement, Fundamentals
from backend.exports.pdf_memo import build_pdf
from backend.exports.xlsx_writer import build_xlsx
from backend.nlp.models import RiskAssessment, RiskOutput
from backend.valuation.dcf import run_dcf
from backend.valuation.engine import ValuationBundle
from backend.valuation.models import AuditFinding
from backend.valuation.sensitivity import sensitivity_table


def _fund() -> Fundamentals:
    return Fundamentals(
        ticker="TEST",
        sector="Technology",
        market_cap=Decimal("10000"),
        beta=Decimal("1.2"),
        price=Decimal("100"),
        statements=[
            FinancialStatement(
                period_end=date(2025, 12, 31),
                revenue=Decimal("1000"),
                net_income=Decimal("150"),
                ebitda=Decimal("300"),
                free_cash_flow=Decimal("180"),
                operating_income=Decimal("200"),
                total_debt=Decimal("2000"),
                cash_and_equivalents=Decimal("500"),
                total_equity=Decimal("3000"),
                shares_outstanding=Decimal("100"),
                interest_expense=Decimal("100"),
                tax_rate=Decimal("0.21"),
            ),
            FinancialStatement(period_end=date(2024, 12, 31), revenue=Decimal("900")),
            FinancialStatement(period_end=date(2023, 12, 31), revenue=Decimal("800")),
            FinancialStatement(period_end=date(2022, 12, 31), revenue=Decimal("700")),
        ],
        as_of=date(2026, 4, 17),
    )


def _bundle() -> ValuationBundle:
    f = _fund()
    dcf = run_dcf(f, risk_free_rate=Decimal("0.04"))
    sens = sensitivity_table(f, base=dcf.assumptions, risk_free_rate=Decimal("0.04"))
    return ValuationBundle(
        dcf=dcf,
        sensitivity=sens,
        monte_carlo=None,
        audit=[AuditFinding(rule="ok", ok=True, detail="fine")],
        auditor_ok=True,
    )


def _comps() -> CompsResult:
    return CompsResult(
        target="TEST",
        peers=[
            PeerRow(symbol="A", market_cap=Decimal("5000"), pe_ratio=Decimal("20"), ev_ebitda=Decimal("12")),
            PeerRow(symbol="B", market_cap=Decimal("3000"), pe_ratio=Decimal("25"), ev_ebitda=Decimal("15")),
        ],
        weighted_pe=Decimal("21.875"),
        weighted_ev_ebitda=Decimal("13.125"),
        median_pe=Decimal("22.5"),
        median_ev_ebitda=Decimal("13.5"),
        implied_price_pe=Decimal("33.75"),
        implied_price_ev_ebitda=Decimal("40.0"),
    )


def _risk() -> RiskOutput:
    a = RiskAssessment(
        legal_risk=1, regulatory_risk=2, macro_risk=1, competitive_risk=2,
        summary="Typical tech risk profile.", top_risks=["ip litigation", "export controls"],
    )
    return RiskOutput(ticker="TEST", assessment=a, discount_rate_adjustment=Decimal("0.0198"), source="haiku")


def test_build_xlsx_writes_file(tmp_path: Path) -> None:
    out = tmp_path / "TEST.xlsx"
    path = build_xlsx(out, _bundle(), _comps(), _risk())
    assert path.exists()
    assert path.stat().st_size > 2_000


def test_build_pdf_writes_file(tmp_path: Path) -> None:
    out = tmp_path / "TEST.pdf"
    path = build_pdf(out, _bundle(), _comps(), _risk())
    assert path.exists()
    assert path.stat().st_size > 1_000
    with open(path, "rb") as fh:
        head = fh.read(4)
    assert head == b"%PDF"
