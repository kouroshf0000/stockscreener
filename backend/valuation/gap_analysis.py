from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.comps.engine import CompsResult
from backend.data_providers.models import Fundamentals
from backend.news.engine import NewsSentiment
from backend.nlp.models import RiskOutput
from backend.technicals.engine import TechnicalSnapshot
from backend.valuation.aggregator import BlendedTarget
from backend.valuation.models import DCFResult

GapDirection = Literal["undervalued", "overvalued", "aligned", "unknown"]
GapSeverity = Literal["low", "moderate", "high"]
DriverImpact = Literal["widening", "countervailing", "mixed"]


class GapDriver(BaseModel):
    model_config = ConfigDict(frozen=True)
    category: str
    signal: str
    impact: DriverImpact
    weight: Literal["high", "medium", "low"]
    detail: str


class ValuationGapAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True)
    triggered: bool
    threshold_pct: Decimal
    gap_pct: Decimal | None
    target_price: Decimal | None
    current_price: Decimal | None
    direction: GapDirection
    severity: GapSeverity
    headline: str
    summary: str
    industry_context: str
    primary_explanation: str
    drivers: list[GapDriver]
    monitoring_points: list[str]


def _q(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal("0.0001"))


def _fmt_pct(value: Decimal | None) -> str:
    if value is None:
        return "n/a"
    return f"{(value * Decimal(100)).quantize(Decimal('0.1'))}%"


def _fmt_money(value: Decimal | None) -> str:
    if value is None:
        return "n/a"
    return f"${value.quantize(Decimal('0.01')):,.2f}"


def _fmt_num(value: Decimal | None) -> str:
    if value is None:
        return "n/a"
    return f"{value.quantize(Decimal('0.01'))}"


def _industry_profile(f: Fundamentals, regime: str | None) -> tuple[Decimal, str, list[str]]:
    sector = (f.sector or "Unknown sector").strip()
    industry = (f.industry or "broad industry").strip()
    key = f"{sector} {industry}".lower()

    threshold = Decimal("0.15")
    framing = "valuation gaps usually close when execution and peer anchoring line up."
    monitors = ["watch estimate revisions versus peer group", "track whether price action starts confirming the target"]

    if regime == "early_stage":
        threshold = Decimal("0.25")
        framing = "early-stage names can stay dislocated for longer because markets anchor more heavily to revenue durability and financing conditions."
        monitors = [
            "watch revenue multiple direction across the peer set",
            "track financing conditions and duration-sensitive sentiment",
        ]
    elif "technology" in key or "software" in key or "semiconductor" in key or "internet" in key:
        threshold = Decimal("0.18")
        framing = "technology valuation gaps tend to reflect duration, product-cycle, and multiple-compression risk more than balance-sheet stress."
        monitors = [
            "watch peer multiple expansion or compression",
            "track product-cycle and demand commentary",
        ]
    elif "healthcare" in key or "biotech" in key or "pharma" in key:
        threshold = Decimal("0.20")
        framing = "healthcare gaps can stay wide when regulatory timing, trial flow, or reimbursement risk dominates near-term price discovery."
        monitors = [
            "watch regulatory and clinical catalysts",
            "track reimbursement and payer commentary",
        ]
    elif "financial" in key or "bank" in key or "insurance" in key:
        threshold = Decimal("0.12")
        framing = "financials usually re-rate around credit quality, capital return, and spread expectations rather than long-duration DCF assumptions."
        monitors = [
            "watch net interest margin and credit trends",
            "track capital return and reserve commentary",
        ]
    elif "energy" in key or "oil" in key or "gas" in key:
        threshold = Decimal("0.16")
        framing = "energy valuation gaps often track commodity expectations and capital discipline rather than static point-in-time earnings multiples."
        monitors = [
            "watch commodity deck changes",
            "track capex discipline and free-cash-flow conversion",
        ]
    elif "utility" in key or "utilities" in key or "consumer defensive" in key or "staples" in key:
        threshold = Decimal("0.10")
        framing = "defensive sectors usually deserve tighter valuation bands because cash flows and peer relationships are more stable."
        monitors = [
            "watch rate sensitivity and dividend support",
            "track relative valuation versus direct peers",
        ]
    elif "industrial" in key or "transport" in key or "capital markets" in key:
        threshold = Decimal("0.14")
        framing = "cyclical sectors typically trade around order momentum, margin durability, and macro expectations."
        monitors = [
            "watch order book and margin commentary",
            "track macro and capex expectations",
        ]

    context = f"{sector} / {industry}: {framing}"
    return threshold, context, monitors


def _method_price(blended: BlendedTarget | None, name: str) -> Decimal | None:
    if blended is None:
        return None
    row = next((row for row in blended.methodology_weights if row.name == name), None)
    return row.implied_price if row else None


def _driver(
    category: str,
    signal: str,
    detail: str,
    impact: DriverImpact,
    weight: Literal["high", "medium", "low"] = "medium",
) -> GapDriver:
    return GapDriver(category=category, signal=signal, detail=detail, impact=impact, weight=weight)


def build_gap_analysis(
    fundamentals: Fundamentals,
    dcf: DCFResult,
    blended: BlendedTarget | None,
    comps: CompsResult | None,
    technicals: TechnicalSnapshot | None,
    news: NewsSentiment | None,
    risk: RiskOutput | None,
) -> ValuationGapAnalysis:
    target_price = blended.price if blended and blended.price is not None else dcf.implied_share_price
    current_price = dcf.current_price
    if current_price is None or current_price <= 0 or target_price is None or target_price <= 0:
        return ValuationGapAnalysis(
            triggered=False,
            threshold_pct=Decimal("0.15"),
            gap_pct=None,
            target_price=target_price,
            current_price=current_price,
            direction="unknown",
            severity="low",
            headline="Insufficient pricing context",
            summary="Current price or target price is unavailable, so the dashboard cannot assess whether the valuation gap is meaningful.",
            industry_context=f"{fundamentals.sector or 'Unknown sector'} / {fundamentals.industry or 'Unknown industry'}",
            primary_explanation="Gap analysis requires both a live market price and an implied value.",
            drivers=[],
            monitoring_points=["restore current price and valuation output"],
        )

    gap_pct = (target_price - current_price) / current_price
    direction: GapDirection
    if abs(gap_pct) < Decimal("0.03"):
        direction = "aligned"
    else:
        direction = "undervalued" if gap_pct > 0 else "overvalued"

    threshold, industry_context, monitoring_points = _industry_profile(fundamentals, blended.regime if blended else None)
    abs_gap = abs(gap_pct)
    triggered = abs_gap >= threshold
    if abs_gap >= threshold * Decimal("2"):
        severity: GapSeverity = "high"
    elif abs_gap >= threshold * Decimal("1.35"):
        severity = "moderate"
    else:
        severity = "low"

    observed_gap = "market discount" if direction == "undervalued" else "market premium"
    drivers: list[GapDriver] = []

    dcf_price = dcf.implied_share_price
    pe_price = next((m.implied_price for m in comps.multiples if m.name == "P/E"), None) if comps else None
    ev_ebitda_price = next((m.implied_price for m in comps.multiples if m.name == "EV/EBITDA"), None) if comps else None
    ev_revenue_price = next((m.implied_price for m in comps.multiples if m.name == "EV/Revenue"), None) if comps else None

    if comps and len(comps.peers) >= 3:
        supporting_prices = [p for p in [pe_price, ev_ebitda_price, ev_revenue_price] if p is not None]
        if supporting_prices:
            avg_comp = sum(supporting_prices, Decimal(0)) / Decimal(len(supporting_prices))
            comp_gap = (avg_comp - current_price) / current_price if current_price else None
            same_side = comp_gap is not None and ((gap_pct > 0 and comp_gap > 0) or (gap_pct < 0 and comp_gap < 0))
            impact: DriverImpact = "widening" if same_side else "countervailing"
            detail = (
                f"Peer-based valuation averages around {_fmt_money(avg_comp)}, versus market price {_fmt_money(current_price)}. "
                f"Current name trades at {_fmt_pct(next((m.premium_discount for m in comps.multiples if m.name == 'EV/EBITDA'), None))} "
                f"to median EV/EBITDA and {_fmt_pct(next((m.premium_discount for m in comps.multiples if m.name == 'P/E'), None))} to median P/E."
            )
            drivers.append(_driver("Comps", "Peer valuation anchor", detail, impact, "high"))

    if technicals is not None:
        weak_for_discount = (
            direction == "undervalued"
            and (technicals.trend == "downtrend" or (technicals.rel_strength_vs_spx is not None and technicals.rel_strength_vs_spx < Decimal("0")))
        )
        strong_for_premium = (
            direction == "overvalued"
            and (technicals.trend == "uptrend" or (technicals.rel_strength_vs_spx is not None and technicals.rel_strength_vs_spx > Decimal("0")))
        )
        impact = "widening" if weak_for_discount or strong_for_premium else "countervailing"
        detail = (
            f"Trend is {technicals.trend}; RSI is {_fmt_num(technicals.rsi_14)} and relative strength vs SPX is {_fmt_pct(technicals.rel_strength_vs_spx)}. "
            f"The stock sits {_fmt_pct(technicals.distance_from_52w_high)} from the 52-week high."
        )
        drivers.append(_driver("Technicals", "Market tape", detail, impact, "medium"))

    if news is not None:
        bearish_for_discount = direction == "undervalued" and news.sentiment == "bearish"
        bullish_for_premium = direction == "overvalued" and news.sentiment == "bullish"
        impact = "widening" if bearish_for_discount or bullish_for_premium else "countervailing" if news.sentiment != "neutral" else "mixed"
        detail = (
            f"Headline tone is {news.sentiment} with score {news.score:+d}. "
            f"Catalysts: {', '.join(news.catalysts) if news.catalysts else 'none highlighted'}. "
            f"Concerns: {', '.join(news.concerns) if news.concerns else 'none highlighted'}."
        )
        drivers.append(_driver("News", "Near-term narrative", detail, impact, "medium"))

    if risk is not None:
        avg_risk = Decimal(
            risk.assessment.legal_risk
            + risk.assessment.regulatory_risk
            + risk.assessment.macro_risk
            + risk.assessment.competitive_risk
        ) / Decimal(4)
        risk_widens_discount = direction == "undervalued" and avg_risk >= Decimal("1.5")
        risk_widens_premium = direction == "overvalued" and avg_risk <= Decimal("1")
        impact = "widening" if risk_widens_discount or risk_widens_premium else "mixed"
        detail = (
            f"Risk adjustment adds {_fmt_pct(risk.discount_rate_adjustment)} to discount rate assumptions. "
            f"Top risks: {', '.join(risk.assessment.top_risks) if risk.assessment.top_risks else risk.assessment.summary}."
        )
        drivers.append(_driver("Risk", "Filing and policy risk", detail, impact, "high" if avg_risk >= Decimal("1.5") else "medium"))

    if blended is not None:
        impact = "countervailing" if blended.confidence == "low" else "mixed"
        detail = (
            f"Blend confidence is {blended.confidence}; regime is {blended.regime}. "
            f"{len(blended.quality_flags)} quality flags were raised across derivation, comps, and technical inputs."
        )
        drivers.append(_driver("Model Quality", "Target robustness", detail, impact, "medium"))

    if blended is not None and blended.regime == "early_stage":
        drivers.append(_driver(
            "Industry Structure",
            "Regime sensitivity",
            "The valuation stack leans more heavily on revenue-stage frameworks and market appetite for duration, so gaps can persist longer than in mature cash-flow stories.",
            "mixed",
            "medium",
        ))

    drivers = drivers[:5]

    widening_drivers = [d for d in drivers if d.impact == "widening"]
    counter_drivers = [d for d in drivers if d.impact == "countervailing"]

    if direction == "undervalued":
        headline = f"{fundamentals.ticker} shows a {severity} market discount to implied value"
        if widening_drivers:
            primary = f"The discount looks driven mainly by {widening_drivers[0].category.lower()} rather than by a single broken valuation input."
        else:
            primary = "The discount is real, but the signal stack is mixed rather than overwhelmingly bearish."
    elif direction == "overvalued":
        headline = f"{fundamentals.ticker} trades at a {severity} market premium to implied value"
        if widening_drivers:
            primary = f"The premium appears to be supported mainly by {widening_drivers[0].category.lower()} and near-term market sponsorship."
        else:
            primary = "The premium exists, but the supporting signals are not uniformly strong."
    else:
        headline = f"{fundamentals.ticker} trades broadly in line with implied value"
        primary = "Market price and modeled value are close enough that any disagreement looks ordinary for the industry."

    summary = (
        f"Current price {_fmt_money(current_price)} versus target {_fmt_money(target_price)} implies a {_fmt_pct(gap_pct)} spread. "
        f"For {fundamentals.sector or 'this sector'} / {fundamentals.industry or 'this industry'}, the dashboard treats moves beyond {_fmt_pct(threshold)} as significant."
    )
    if counter_drivers:
        summary += f" Counter-signals are coming from {counter_drivers[0].category.lower()}."

    return ValuationGapAnalysis(
        triggered=triggered,
        threshold_pct=_q(threshold) or threshold,
        gap_pct=_q(gap_pct),
        target_price=target_price.quantize(Decimal("0.01")),
        current_price=current_price.quantize(Decimal("0.01")),
        direction=direction,
        severity=severity,
        headline=headline,
        summary=summary,
        industry_context=industry_context,
        primary_explanation=primary,
        drivers=drivers,
        monitoring_points=monitoring_points[:3],
    )
