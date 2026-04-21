from __future__ import annotations

from decimal import Decimal

from backend.comps.engine import CompsResult, MultipleStat, PeerRow
from backend.valuation.football_field import build_football_field
from backend.valuation.scenarios import Scenario, ScenarioBundle


def _scenarios() -> ScenarioBundle:
    return ScenarioBundle(
        bull=Scenario(name="bull", implied_price=Decimal("150"), upside_pct=Decimal("0.5"), description=""),
        base=Scenario(name="base", implied_price=Decimal("120"), upside_pct=Decimal("0.2"), description=""),
        bear=Scenario(name="bear", implied_price=Decimal("80"), upside_pct=Decimal("-0.2"), description=""),
    )


def _comps() -> CompsResult:
    m = [
        MultipleStat(name="P/E", target=Decimal("20"), peer_median=Decimal("22"), peer_weighted=Decimal("21"), premium_discount=Decimal("-0.09"), implied_price=Decimal("110")),
        MultipleStat(name="EV/EBITDA", target=Decimal("12"), peer_median=Decimal("14"), peer_weighted=Decimal("13"), premium_discount=Decimal("-0.14"), implied_price=Decimal("130")),
    ]
    return CompsResult(
        target="TEST",
        peers=[PeerRow(symbol="A", market_cap=Decimal("1000"), pe_ratio=Decimal("22"), ev_ebitda=Decimal("14"))],
        peer_selection_method="curated override",
        multiples=m,
        weighted_pe=Decimal("21"),
        weighted_ev_ebitda=Decimal("13"),
        median_pe=Decimal("22"),
        median_ev_ebitda=Decimal("14"),
        implied_price_pe=Decimal("110"),
        implied_price_ev_ebitda=Decimal("130"),
    )


def test_football_field_ranges() -> None:
    ff = build_football_field(
        current_price=Decimal("100"),
        scenarios=_scenarios(),
        comps=_comps(),
        technicals=None,
    )
    labels = [r.label for r in ff.rows]
    assert "DCF (bear/base/bull)" in labels
    assert "Trading comps (implied range)" in labels
    dcf_row = next(r for r in ff.rows if r.label.startswith("DCF"))
    assert dcf_row.low == Decimal("80")
    assert dcf_row.high == Decimal("150")
    comps_row = next(r for r in ff.rows if r.label.startswith("Trading"))
    assert comps_row.low == Decimal("110")
    assert comps_row.high == Decimal("130")
