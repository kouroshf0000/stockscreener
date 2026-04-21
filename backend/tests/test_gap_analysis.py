from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from backend.comps.engine import CompsResult, MultipleStat, PeerRow
from backend.data_providers.models import FinancialStatement, Fundamentals
from backend.news.engine import NewsSentiment
from backend.nlp.models import RiskAssessment, RiskOutput
from backend.technicals.engine import TechnicalSnapshot
from backend.valuation.aggregator import build_blended_target
from backend.valuation.gap_analysis import build_gap_analysis
from backend.valuation.models import Assumptions, DCFResult, ProjectionRow, WACCBreakdown
from backend.valuation.scenarios import Scenario, ScenarioBundle


def _fund(sector: str = "Technology", industry: str = "Semiconductors") -> Fundamentals:
    return Fundamentals(
        ticker="TEST",
        name="Test Corp",
        sector=sector,
        industry=industry,
        market_cap=Decimal("8000"),
        beta=Decimal("1.2"),
        price=Decimal("80"),
        statements=[
            FinancialStatement(
                period_end=date(2025, 12, 31),
                revenue=Decimal("2000"),
                operating_income=Decimal("450"),
                net_income=Decimal("300"),
                ebitda=Decimal("600"),
                free_cash_flow=Decimal("280"),
                total_debt=Decimal("500"),
                cash_and_equivalents=Decimal("300"),
                total_equity=Decimal("2200"),
                shares_outstanding=Decimal("100"),
                tax_rate=Decimal("0.21"),
            )
        ],
        as_of=date(2026, 4, 17),
    )


def _dcf(current: str = "80", implied: str = "125") -> DCFResult:
    return DCFResult(
        ticker="TEST",
        as_of=date(2026, 4, 17),
        wacc=WACCBreakdown(
            cost_of_equity=Decimal("0.10"),
            cost_of_debt_after_tax=Decimal("0.04"),
            weight_equity=Decimal("0.8"),
            weight_debt=Decimal("0.2"),
            wacc=Decimal("0.088"),
        ),
        assumptions=Assumptions(),
        projections=[
            ProjectionRow(
                year=2026,
                revenue=Decimal("2100"),
                ebit=Decimal("460"),
                nopat=Decimal("360"),
                reinvestment=Decimal("120"),
                fcff=Decimal("240"),
                discount_factor=Decimal("0.92"),
                pv_fcff=Decimal("220"),
            )
        ],
        pv_explicit=Decimal("900"),
        terminal_value=Decimal("10000"),
        pv_terminal=Decimal("7000"),
        enterprise_value=Decimal("7900"),
        net_debt=Decimal("200"),
        equity_value=Decimal("7700"),
        shares_outstanding=Decimal("100"),
        implied_share_price=Decimal(implied),
        current_price=Decimal(current),
        upside_pct=(Decimal(implied) - Decimal(current)) / Decimal(current),
        red_flags=[],
    )


def _comps() -> CompsResult:
    return CompsResult(
        target="TEST",
        peers=[
            PeerRow(symbol="A", market_cap=Decimal("4000"), pe_ratio=Decimal("22"), ev_ebitda=Decimal("13")),
            PeerRow(symbol="B", market_cap=Decimal("5000"), pe_ratio=Decimal("24"), ev_ebitda=Decimal("14")),
            PeerRow(symbol="C", market_cap=Decimal("6000"), pe_ratio=Decimal("26"), ev_ebitda=Decimal("15")),
        ],
        peer_selection_method="auto: sector+industry+size-band",
        multiples=[
            MultipleStat(name="P/E", target=Decimal("18"), peer_median=Decimal("24"), peer_weighted=Decimal("24.4"), premium_discount=Decimal("-0.25"), implied_price=Decimal("120")),
            MultipleStat(name="EV/EBITDA", target=Decimal("10"), peer_median=Decimal("14"), peer_weighted=Decimal("14.2"), premium_discount=Decimal("-0.2857"), implied_price=Decimal("132")),
            MultipleStat(name="EV/Revenue", target=Decimal("3"), peer_median=Decimal("4"), peer_weighted=Decimal("4.1"), premium_discount=Decimal("-0.25"), implied_price=Decimal("118")),
        ],
        median_pe=Decimal("24"),
        median_ev_ebitda=Decimal("14"),
        implied_price_pe=Decimal("120"),
        implied_price_ev_ebitda=Decimal("132"),
    )


def _technicals(trend: str = "downtrend") -> TechnicalSnapshot:
    return TechnicalSnapshot(
        ticker="TEST",
        as_of=date(2026, 4, 17),
        price=Decimal("80"),
        sma_50=Decimal("88"),
        sma_200=Decimal("96"),
        rsi_14=Decimal("42"),
        macd=Decimal("-1.2"),
        macd_signal=Decimal("-0.8"),
        macd_hist=Decimal("-0.4"),
        w52_high=Decimal("110"),
        w52_low=Decimal("70"),
        distance_from_52w_high=Decimal("-0.2727"),
        distance_from_52w_low=Decimal("0.1429"),
        rel_strength_vs_spx=Decimal("-0.12"),
        trend=trend,  # type: ignore[arg-type]
    )


def _news(sentiment: str = "bearish", score: int = -2) -> NewsSentiment:
    return NewsSentiment(
        ticker="TEST",
        as_of=date(2026, 4, 17),
        items_reviewed=5,
        sentiment=sentiment,  # type: ignore[arg-type]
        score=score,
        catalysts=["inventory normalization"],
        concerns=["demand pause", "multiple compression"],
        summary="Near-term headlines remain cautious.",
        source="haiku",
    )


def _risk() -> RiskOutput:
    return RiskOutput(
        ticker="TEST",
        assessment=RiskAssessment(
            legal_risk=1,
            regulatory_risk=1,
            macro_risk=2,
            competitive_risk=2,
            summary="Cyclicality and competition remain the main pressure points.",
            top_risks=["inventory digestion", "pricing pressure"],
        ),
        discount_rate_adjustment=Decimal("0.0132"),
        source="haiku",
    )


@pytest.mark.asyncio
async def test_gap_analysis_flags_large_discount_as_significant() -> None:
    fund = _fund()
    dcf = _dcf()
    blended = await build_blended_target(
        scenarios=ScenarioBundle(
            bull=Scenario(name="bull", implied_price=Decimal("145"), upside_pct=Decimal("0.8125"), description="bull"),
            base=Scenario(name="base", implied_price=Decimal("125"), upside_pct=Decimal("0.5625"), description="base"),
            bear=Scenario(name="bear", implied_price=Decimal("95"), upside_pct=Decimal("0.1875"), description="bear"),
        ),
        comps=_comps(),
        technicals=_technicals(),
        risk=_risk(),
        current_price=Decimal("80"),
        provenance={"revenue_growth": "derived from historical growth"},
    )
    analysis = build_gap_analysis(
        fundamentals=fund,
        dcf=dcf,
        blended=blended,
        comps=_comps(),
        technicals=_technicals(),
        news=_news(),
        risk=_risk(),
    )

    assert analysis.triggered is True
    assert analysis.direction == "undervalued"
    assert analysis.severity in {"moderate", "high"}
    assert "Technology / Semiconductors" in analysis.industry_context
    assert analysis.drivers
    assert any(driver.category == "Comps" for driver in analysis.drivers)


@pytest.mark.asyncio
async def test_gap_analysis_uses_tighter_band_for_defensives() -> None:
    fund = _fund(sector="Utilities", industry="Electric Utilities")
    dcf = _dcf(current="100", implied="108")
    blended = await build_blended_target(
        scenarios=ScenarioBundle(
            bull=Scenario(name="bull", implied_price=Decimal("112"), upside_pct=Decimal("0.12"), description="bull"),
            base=Scenario(name="base", implied_price=Decimal("108"), upside_pct=Decimal("0.08"), description="base"),
            bear=Scenario(name="bear", implied_price=Decimal("101"), upside_pct=Decimal("0.01"), description="bear"),
        ),
        comps=None,
        technicals=None,
        risk=None,
        current_price=Decimal("100"),
        provenance={},
    )
    analysis = build_gap_analysis(
        fundamentals=fund,
        dcf=dcf,
        blended=blended,
        comps=None,
        technicals=None,
        news=None,
        risk=None,
    )

    assert analysis.threshold_pct == Decimal("0.1000")
    assert analysis.triggered is False
    assert analysis.direction == "undervalued"
