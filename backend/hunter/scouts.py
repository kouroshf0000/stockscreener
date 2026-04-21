from __future__ import annotations

from decimal import Decimal

from backend.data_providers.models import Fundamentals
from backend.hunter.models import ScoutScore
from backend.screener.metrics import (
    compute_all,
    debt_to_equity,
    ev_ebitda,
    fcf_yield,
    pe_ratio,
    revenue_cagr_3y,
    roic,
)


async def _hedge_fund_conviction(cusip: str | None) -> Decimal:
    """Returns 0–1 score based on how many watchlist funds hold this stock."""
    if not cusip:
        return Decimal("0")
    try:
        from backend.filings.thirteenf import fetch_holders_for_ticker

        holders = await fetch_holders_for_ticker(cusip, quarters=1)
        # 3+ holders = full score, linear below
        count = len(holders)
        return min(Decimal(str(count)) / Decimal("3"), Decimal("1"))
    except Exception:
        return Decimal("0")


def _cap(x: float, lo: float = 0, hi: float = 100) -> Decimal:
    return Decimal(str(round(max(lo, min(hi, x)), 2)))


def score_value(f: Fundamentals, sector_median_pe: Decimal | None = None) -> ScoutScore:
    evidence: list[str] = []
    pts = 50.0
    pe = pe_ratio(f)
    fcfy = fcf_yield(f)
    evm = ev_ebitda(f)

    if pe is not None and sector_median_pe is not None and sector_median_pe > 0:
        ratio = float(pe) / float(sector_median_pe)
        if ratio < 0.8:
            pts += 20
            evidence.append(f"P/E {pe:.1f} is {(1 - ratio) * 100:.0f}% below sector median")
        elif ratio > 1.3:
            pts -= 15

    if fcfy is not None:
        if fcfy > Decimal("0.05"):
            pts += 15
            evidence.append(f"FCF yield {float(fcfy) * 100:.1f}% > 5%")
        elif fcfy < 0:
            pts -= 20

    if evm is not None and evm < Decimal("10"):
        pts += 10
        evidence.append(f"EV/EBITDA {evm:.1f} < 10")

    return ScoutScore(scout="value", score=_cap(pts), evidence=evidence)


def score_quality(f: Fundamentals) -> ScoutScore:
    evidence: list[str] = []
    pts = 50.0
    r = roic(f)
    dte = debt_to_equity(f)
    cagr = revenue_cagr_3y(f)

    if r is not None:
        if r > Decimal("0.15"):
            pts += 20
            evidence.append(f"ROIC {float(r) * 100:.1f}% > 15%")
        elif r < 0:
            pts -= 25

    if dte is not None:
        if dte < Decimal("1"):
            pts += 10
            evidence.append(f"Debt/Equity {dte:.2f} < 1")
        elif dte > Decimal("3"):
            pts -= 15

    if cagr is not None:
        if cagr > Decimal("0.10"):
            pts += 15
            evidence.append(f"3Y revenue CAGR {float(cagr) * 100:.1f}% > 10%")
        elif cagr < 0:
            pts -= 20

    return ScoutScore(scout="quality", score=_cap(pts), evidence=evidence)


def score_momentum(f: Fundamentals) -> ScoutScore:
    evidence: list[str] = []
    pts = 50.0
    cagr = revenue_cagr_3y(f)
    if cagr is not None and cagr > Decimal("0.15"):
        pts += 20
        evidence.append(f"Revenue growing {float(cagr) * 100:.1f}% 3Y CAGR")

    m = compute_all(f)
    pe = m["pe_ratio"]
    fcfy = m["fcf_yield"]
    if pe is not None and pe > 0 and pe < Decimal("40"):
        pts += 10
        evidence.append("P/E reasonable for growth profile")
    if fcfy is not None and fcfy > 0:
        pts += 10
        evidence.append("Positive FCF yield confirms growth is cash-backed")
    return ScoutScore(scout="momentum", score=_cap(pts), evidence=evidence)


def score_catalyst(f: Fundamentals, risk_level_total: int | None = None) -> ScoutScore:
    """Synchronous catalyst score (no hedge fund conviction). Use score_catalyst_async for full scoring."""
    evidence: list[str] = []
    pts = 50.0
    if risk_level_total is not None:
        if risk_level_total <= 4:
            pts += 15
            evidence.append(f"Risk profile benign (total {risk_level_total}/12)")
        elif risk_level_total >= 9:
            pts -= 15

    if f.statements and len(f.statements) >= 2:
        a, b = f.statements[0], f.statements[1]
        if a.free_cash_flow and b.free_cash_flow and b.free_cash_flow > 0:
            growth = float(a.free_cash_flow) / float(b.free_cash_flow) - 1
            if growth > 0.15:
                pts += 10
                evidence.append(f"FCF inflection: +{growth * 100:.0f}% YoY")

    return ScoutScore(scout="catalyst", score=_cap(pts), evidence=evidence)


async def score_catalyst_async(
    f: Fundamentals,
    risk_level_total: int | None = None,
    cusip: str | None = None,
) -> ScoutScore:
    """Async catalyst score that incorporates 15% hedge fund conviction weight."""
    base = score_catalyst(f, risk_level_total=risk_level_total)

    conviction = await _hedge_fund_conviction(cusip)
    # Apply 15% weight: scale conviction (0–1) to pts contribution (0–15)
    hf_pts = float(conviction) * 15.0
    adjusted_pts = float(base.score) + hf_pts
    evidence = list(base.evidence)
    if conviction > Decimal("0"):
        evidence.append(f"Hedge fund conviction score: {float(conviction):.2f} ({hf_pts:.1f} pts)")

    return ScoutScore(scout="catalyst", score=_cap(adjusted_pts), evidence=evidence)
