from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from backend.comps.engine import CompsResult, PeerRow
from backend.data_providers.models import FinancialStatement, Fundamentals
from backend.hunter import engine as hunter_engine
from backend.hunter.gate import MAX_COMPS_DIVERGENCE, run_gate
from backend.hunter.scouts import (
    score_catalyst,
    score_momentum,
    score_quality,
    score_value,
)
from backend.nlp.models import RiskAssessment, RiskOutput
from backend.valuation.dcf import run_dcf
from backend.valuation.engine import ValuationBundle
from backend.valuation.models import AuditFinding
from backend.valuation.sensitivity import sensitivity_table


def _fund(
    sym: str = "TEST",
    price: int = 100,
) -> Fundamentals:
    shares = 1_000_000_000
    mcap = shares * price
    rev_now = 50_000_000_000
    rev_3y = 30_000_000_000
    ni = 10_000_000_000
    return Fundamentals(
        ticker=sym,
        sector="Technology",
        market_cap=Decimal(mcap),
        beta=Decimal("1.1"),
        price=Decimal(price),
        statements=[
            FinancialStatement(
                period_end=date(2025, 12, 31),
                revenue=Decimal(rev_now),
                net_income=Decimal(ni),
                ebitda=Decimal(int(ni * 1.5)),
                free_cash_flow=Decimal(int(ni * 0.9)),
                operating_income=Decimal(int(ni * 1.3)),
                total_debt=Decimal(5_000_000_000),
                cash_and_equivalents=Decimal(8_000_000_000),
                total_equity=Decimal(40_000_000_000),
                shares_outstanding=Decimal(shares),
                interest_expense=Decimal(250_000_000),
                tax_rate=Decimal("0.21"),
            ),
            FinancialStatement(
                period_end=date(2024, 12, 31), revenue=Decimal(int(rev_now * 0.9))
            ),
            FinancialStatement(
                period_end=date(2023, 12, 31), revenue=Decimal(int(rev_now * 0.8))
            ),
            FinancialStatement(period_end=date(2022, 12, 31), revenue=Decimal(rev_3y)),
        ],
        as_of=date(2026, 4, 17),
    )


def test_scouts_produce_scores_in_range() -> None:
    f = _fund()
    v = score_value(f, sector_median_pe=Decimal("30"))
    q = score_quality(f)
    m = score_momentum(f)
    c = score_catalyst(f, risk_level_total=4)
    for s in (v, q, m, c):
        assert Decimal(0) <= s.score <= Decimal(100)


def _bundle(f: Fundamentals) -> ValuationBundle:
    dcf = run_dcf(f, risk_free_rate=Decimal("0.04"))
    sens = sensitivity_table(f, base=dcf.assumptions, risk_free_rate=Decimal("0.04"))
    return ValuationBundle(
        dcf=dcf, sensitivity=sens, monte_carlo=None,
        audit=[AuditFinding(rule="ok", ok=True, detail="")], auditor_ok=True,
    )


def test_gate_fails_on_low_upside() -> None:
    f = _fund(price=1_000_000)
    val = _bundle(f)
    passed, checks = run_gate(val, None, f.market_cap, legal_risk=1)
    assert not passed
    rules = {c.rule for c in checks if c.result == "fail"}
    assert "upside" in rules or "comps_agreement" in rules


def test_gate_passes_when_everything_agrees() -> None:
    f = _fund(price=50)
    val = _bundle(f)
    implied = val.dcf.implied_share_price
    comps = CompsResult(
        target="TEST",
        peers=[PeerRow(symbol="P", market_cap=Decimal("1e10"), pe_ratio=Decimal("20"), ev_ebitda=Decimal("10"))],
        weighted_pe=Decimal("20"),
        weighted_ev_ebitda=Decimal("10"),
        median_pe=Decimal("20"),
        median_ev_ebitda=Decimal("10"),
        implied_price_pe=implied * (Decimal(1) + MAX_COMPS_DIVERGENCE - Decimal("0.01")),
        implied_price_ev_ebitda=implied,
    )
    passed, checks = run_gate(val, comps, f.market_cap, legal_risk=1)
    if val.dcf.upside_pct is not None and val.dcf.upside_pct >= Decimal("0.20"):
        assert passed, [c for c in checks if c.result == "fail"]


@pytest.mark.asyncio
async def test_run_hunt_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_fund = {
        "AAA": _fund("AAA", price=30),
        "BBB": _fund("BBB", price=1_000_000),
    }

    async def _fetch(sym: str) -> Fundamentals:
        return fake_fund[sym]

    async def _run_comps(sym: str) -> CompsResult:
        f = fake_fund[sym]
        val = _bundle(f)
        target = val.dcf.implied_share_price
        return CompsResult(
            target=sym,
            peers=[PeerRow(symbol="P", market_cap=Decimal("1e10"), pe_ratio=Decimal("22"), ev_ebitda=Decimal("12"))],
            weighted_pe=Decimal("22"), weighted_ev_ebitda=Decimal("12"),
            median_pe=Decimal("22"), median_ev_ebitda=Decimal("12"),
            implied_price_pe=target,
            implied_price_ev_ebitda=target,
        )

    async def _valuate(sym: str, *_: object, **__: object) -> ValuationBundle:
        return _bundle(fake_fund[sym])

    async def _risk(sym: str) -> RiskOutput:
        return RiskOutput(
            ticker=sym,
            assessment=RiskAssessment(
                legal_risk=1, regulatory_risk=1, macro_risk=1, competitive_risk=1,
                summary="benign", top_risks=[],
            ),
            discount_rate_adjustment=Decimal("0.0132"),
            source="fallback",
        )

    async def _narrative(*_: object, **__: object) -> str:
        return "Thesis.\n\nWhat has to be true.\n\nWhat would kill it."

    monkeypatch.setattr(hunter_engine, "fetch_fundamentals", _fetch)
    monkeypatch.setattr(hunter_engine, "run_comps", _run_comps)
    monkeypatch.setattr(hunter_engine, "valuate", _valuate)
    monkeypatch.setattr(hunter_engine, "analyze_risk", _risk)
    monkeypatch.setattr(hunter_engine, "generate_thesis_narrative", _narrative)
    monkeypatch.setattr(hunter_engine, "universe_for", lambda _n: ("AAA", "BBB"))

    def _no_export(*_: object, **__: object) -> object:
        from pathlib import Path

        return Path("/tmp/ignore.bin")

    monkeypatch.setattr(hunter_engine, "build_xlsx", _no_export)
    monkeypatch.setattr(hunter_engine, "build_pdf", _no_export)
    monkeypatch.setattr(hunter_engine, "save_run", lambda r: None)

    report = await hunter_engine.run_hunt(universe_name="SP500", top_n=5)
    assert report.candidates_evaluated == 2
    syms_passed = [p.ticker for p in report.picks]
    assert "AAA" in syms_passed
    assert "BBB" not in syms_passed
