from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from backend.comps.engine import CompsResult
from backend.nlp.models import RiskOutput
from backend.technicals.engine import TechnicalSnapshot
from backend.valuation.scenarios import Scenario, ScenarioBundle

if TYPE_CHECKING:
    from backend.data_providers.models import Fundamentals


Severity = Literal["critical", "warning", "note"]


class QualityFlag(BaseModel):
    model_config = ConfigDict(frozen=True)
    severity: Severity
    field: str
    message: str


class MethodologyWeight(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    weight: Decimal
    implied_price: Decimal | None
    weighted_contribution: Decimal | None


class BlendedTarget(BaseModel):
    model_config = ConfigDict(frozen=True)
    price: Decimal | None
    upside_pct: Decimal | None
    current_price: Decimal | None
    rating: Literal["OUTPERFORM", "NEUTRAL", "UNDERPERFORM"] | None
    confidence: Literal["high", "medium", "low"]
    methodology_weights: list[MethodologyWeight]
    quality_flags: list[QualityFlag]
    regime: str
    methodology_note: str | None = None


def _pct(current: Decimal | None, target: Decimal | None) -> Decimal | None:
    if current is None or target is None or current <= 0:
        return None
    return (target - current) / current


def _rating(upside: Decimal | None) -> Literal["OUTPERFORM", "NEUTRAL", "UNDERPERFORM"] | None:
    if upside is None:
        return None
    if upside > Decimal("0.10"):
        return "OUTPERFORM"
    if upside < Decimal("-0.10"):
        return "UNDERPERFORM"
    return "NEUTRAL"


def _regime(
    scenarios: ScenarioBundle | None,
    comps: CompsResult | None,
    risk: RiskOutput | None,
    fundamentals: "Fundamentals | None" = None,
) -> str:
    """Classify company into valuation regime to drive methodology weights."""
    # Pre-profitable: negative EBIT in 2+ of last 3 reported years
    if fundamentals is not None and fundamentals.statements:
        recent = fundamentals.statements[:3]
        neg_ebit = sum(
            1 for s in recent
            if s.operating_income is not None and s.operating_income < Decimal(0)
        )
        if neg_ebit >= 2:
            return "pre_profitable"

    # Loss-making: DCF base price is negligible or negative
    if scenarios is not None:
        base_price = scenarios.base.implied_price
        if base_price is not None and base_price <= Decimal("5"):
            return "early_stage"

    # If comps has EV/Revenue implied prices but P/E is None → revenue-stage
    if comps is not None:
        pe_stat = next((m for m in comps.multiples if m.name == "P/E"), None)
        ev_rev_stat = next((m for m in comps.multiples if m.name == "EV/Revenue"), None)
        if pe_stat and pe_stat.implied_price is None and ev_rev_stat and ev_rev_stat.implied_price:
            return "early_stage"

    return "mature"


def _weights(regime: str) -> dict[str, Decimal]:
    """
    IB-standard methodology weights by regime.
    Mature tech trades at premium multiples that DCF structurally undersells —
    an IB MD would weight comps 60-70% and use DCF as a floor/sanity check.
    """
    if regime == "pre_profitable":
        # DCF inapplicable for loss-making names; EV/Revenue is primary anchor.
        return {
            "DCF": Decimal("0.05"),
            "EV/Revenue": Decimal("0.55"),
            "EV/EBITDA": Decimal("0.10"),
            "52W": Decimal("0.30"),
        }
    if regime == "early_stage":
        return {
            "DCF": Decimal("0.15"),
            "EV/Revenue": Decimal("0.50"),
            "EV/EBITDA": Decimal("0.15"),
            "52W": Decimal("0.20"),
        }
    # Mature companies: comps-led (EV/EBITDA + P/E = 50%), DCF as 35% floor
    return {
        "DCF": Decimal("0.35"),
        "EV/EBITDA": Decimal("0.35"),
        "P/E": Decimal("0.20"),
        "52W": Decimal("0.10"),
    }


def _comp_implied(comps: CompsResult | None, name: str) -> Decimal | None:
    if comps is None:
        return None
    stat = next((m for m in comps.multiples if m.name == name), None)
    if stat is None:
        return None
    return stat.implied_price


def _52w_mid(technicals: TechnicalSnapshot | None) -> Decimal | None:
    if technicals is None or technicals.w52_low is None or technicals.w52_high is None:
        return None
    return (technicals.w52_low + technicals.w52_high) / Decimal(2)


def _quality_flags(
    scenarios: ScenarioBundle | None,
    comps: CompsResult | None,
    technicals: TechnicalSnapshot | None,
    risk: RiskOutput | None,
    provenance: dict[str, str],
    weights: dict[str, Decimal],
    implied_prices: dict[str, Decimal | None],
) -> list[QualityFlag]:
    flags: list[QualityFlag] = []

    # Risk source
    if risk is not None and risk.source == "fallback":
        flags.append(QualityFlag(
            severity="warning",
            field="risk_factors",
            message=f"Risk scored via fallback (reason: {risk.fallback_reason}); discount rate adjustment may be understated.",
        ))

    # DCF provenance notes
    for k, v in provenance.items():
        if "hardcoded" in v.lower() or "missing" in v.lower() or "fallback" in v.lower():
            flags.append(QualityFlag(severity="note", field=k, message=v))
        if "delta_nwc" in k.lower() or "sbc" in k.lower():
            flags.append(QualityFlag(
                severity="note", field=k,
                message=f"Reinvestment component '{k}' not available from yfinance; estimate used.",
            ))

    # Peer sparsity
    if comps is None or len(comps.peers) < 3:
        flags.append(QualityFlag(
            severity="warning",
            field="comps",
            message="Fewer than 3 comparable peers found; trading comps weight may overfit.",
        ))

    # Comp divergence: if P/E implied vs EV/EBITDA implied spread > 50%
    pe_price = implied_prices.get("P/E")
    ev_price = implied_prices.get("EV/EBITDA")
    if pe_price and ev_price and pe_price > 0 and ev_price > 0:
        spread = abs(pe_price - ev_price) / ((pe_price + ev_price) / Decimal(2))
        if spread > Decimal("0.50"):
            flags.append(QualityFlag(
                severity="warning",
                field="comps_divergence",
                message=f"P/E implied (${pe_price:.0f}) vs EV/EBITDA implied (${ev_price:.0f}) spread exceeds 50%; comps are inconsistent.",
            ))

    # Missing 52W data
    if implied_prices.get("52W") is None and "52W" in weights:
        flags.append(QualityFlag(
            severity="note",
            field="technicals",
            message="52-week range unavailable; 52W methodology component excluded from blend.",
        ))

    # No API key for risk scoring
    if risk is None:
        flags.append(QualityFlag(
            severity="note",
            field="risk",
            message="No risk assessment available; discount rate adjustment not applied.",
        ))

    # DCF scenario missing
    if scenarios is None:
        flags.append(QualityFlag(
            severity="warning",
            field="dcf_scenarios",
            message="DCF scenarios unavailable; blended target relies on fallback logic.",
        ))

    return flags


async def _generate_methodology_note(
    ticker: str,
    regime: str,
    weights: dict[str, Decimal],
    fundamentals: "Fundamentals | None",
) -> str | None:
    from anthropic import AsyncAnthropic
    from backend.app.config import get_settings
    settings = get_settings()
    if not settings.anthropic_api_key:
        return None

    stmts = (fundamentals.statements[:3] if fundamentals and fundamentals.statements else [])
    ebit_lines = [
        f"Y{s.period_end.year}: EBIT ${float(s.operating_income) / 1e9:.1f}B"
        for s in stmts if s.operating_income is not None
    ]
    weight_str = ", ".join(f"{k}={float(v):.0%}" for k, v in weights.items())

    prompt = (
        f"You are an equity research MD reviewing {ticker} (regime: {regime}).\n"
        f"EBIT history: {', '.join(ebit_lines) if ebit_lines else 'unavailable'}\n"
        f"Methodology weights: {weight_str}\n\n"
        "In 1-2 sentences, explain why these weights are appropriate and the key caveat for investors. "
        "Be specific to this company's financials, not generic."
    )
    try:
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        msg = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception:
        return None


async def build_blended_target(
    scenarios: ScenarioBundle | None,
    comps: CompsResult | None,
    technicals: TechnicalSnapshot | None,
    risk: RiskOutput | None,
    current_price: Decimal | None,
    provenance: dict[str, str] | None = None,
    fundamentals: "Fundamentals | None" = None,
    ticker: str = "",
) -> BlendedTarget:
    prov = provenance or {}
    regime = _regime(scenarios, comps, risk, fundamentals)
    weights = _weights(regime)

    # Build price map for each methodology
    dcf_price = scenarios.base.implied_price if scenarios else None
    implied: dict[str, Decimal | None] = {
        "DCF": dcf_price,
        "EV/EBITDA": _comp_implied(comps, "EV/EBITDA"),
        "P/E": _comp_implied(comps, "P/E"),
        "EV/Revenue": _comp_implied(comps, "EV/Revenue"),
        "52W": _52w_mid(technicals),
    }

    flags = _quality_flags(scenarios, comps, technicals, risk, prov, weights, implied)

    # Compute weighted blend — skip methodologies with no price
    total_weight = Decimal(0)
    weighted_sum = Decimal(0)
    method_rows: list[MethodologyWeight] = []

    for name, raw_weight in weights.items():
        price = implied.get(name)
        if price is None or price <= 0:
            method_rows.append(MethodologyWeight(
                name=name, weight=raw_weight, implied_price=None, weighted_contribution=None
            ))
            continue
        total_weight += raw_weight
        weighted_sum += raw_weight * price
        method_rows.append(MethodologyWeight(
            name=name,
            weight=raw_weight,
            implied_price=price.quantize(Decimal("0.01")),
            weighted_contribution=(raw_weight * price).quantize(Decimal("0.01")),
        ))

    blended: Decimal | None = None
    if total_weight > 0:
        blended = (weighted_sum / total_weight).quantize(Decimal("0.01"))

    upside = _pct(current_price, blended)
    rating = _rating(upside)

    # Confidence: based on how many methodologies contributed + flag severity
    critical_count = sum(1 for f in flags if f.severity == "critical")
    warning_count = sum(1 for f in flags if f.severity == "warning")
    contributing = sum(1 for r in method_rows if r.implied_price is not None)

    if critical_count > 0 or contributing < 2:
        confidence: Literal["high", "medium", "low"] = "low"
    elif warning_count > 1 or contributing < 3:
        confidence = "medium"
    else:
        confidence = "high"

    methodology_note = await _generate_methodology_note(ticker, regime, weights, fundamentals)

    return BlendedTarget(
        price=blended,
        upside_pct=upside.quantize(Decimal("0.0001")) if upside else None,
        current_price=current_price,
        rating=rating,
        confidence=confidence,
        methodology_weights=method_rows,
        quality_flags=flags,
        regime=regime,
        methodology_note=methodology_note,
    )
