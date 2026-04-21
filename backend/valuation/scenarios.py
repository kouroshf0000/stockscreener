from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from backend.data_providers.fred_client import fetch_risk_free_rate
from backend.data_providers.yfinance_client import fetch_fundamentals
from backend.valuation.dcf import run_dcf
from backend.valuation.derivation import derive_assumptions
from backend.valuation.models import Assumptions, DCFResult


class Scenario(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    implied_price: Decimal
    upside_pct: Decimal | None
    description: str


class ScenarioBundle(BaseModel):
    model_config = ConfigDict(frozen=True)
    bull: Scenario
    base: Scenario
    bear: Scenario


def _shift(a: Assumptions, growth_delta: Decimal, margin_delta: Decimal, terminal_delta: Decimal) -> Assumptions:
    growth = [g + growth_delta for g in a.revenue_growth]
    margin_path = (
        [m + margin_delta for m in a.ebit_margin_path]
        if a.ebit_margin_path is not None
        else None
    )
    return Assumptions(
        revenue_growth=growth,
        ebit_margin=a.ebit_margin + margin_delta,
        ebit_margin_path=margin_path,
        tax_rate=a.tax_rate,
        reinvestment_rate=a.reinvestment_rate,
        reinvestment_rate_path=a.reinvestment_rate_path,
        terminal_growth=a.terminal_growth + terminal_delta,
        equity_risk_premium=a.equity_risk_premium,
        risk_premium_adjustment=a.risk_premium_adjustment,
        exit_multiple_ev_ebitda=a.exit_multiple_ev_ebitda,
    )


async def run_scenarios(ticker: str, peer_ev_ebitda: Decimal | None = None) -> ScenarioBundle:
    f = await fetch_fundamentals(ticker)
    rfr = await fetch_risk_free_rate()
    derived = await derive_assumptions(f, peer_ev_ebitda=peer_ev_ebitda)
    base = derived.assumptions

    def _run(label: str, a: Assumptions, desc: str) -> Scenario:
        r: DCFResult = run_dcf(f, risk_free_rate=rfr.rate, assumptions=a)
        return Scenario(
            name=label,
            implied_price=r.implied_share_price,
            upside_pct=r.upside_pct,
            description=desc,
        )

    bull = _run(
        "bull",
        _shift(base, Decimal("0.02"), Decimal("0.01"), Decimal("0.005")),
        "+200bp revenue growth, +100bp EBIT margin, +50bp terminal growth",
    )
    base_s = _run("base", base, "Derived from filings")
    bear = _run(
        "bear",
        _shift(base, Decimal("-0.02"), Decimal("-0.01"), Decimal("-0.005")),
        "-200bp revenue growth, -100bp EBIT margin, -50bp terminal growth",
    )
    return ScenarioBundle(bull=bull, base=base_s, bear=bear)
