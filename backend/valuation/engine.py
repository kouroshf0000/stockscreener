from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from backend.comps.engine import CompsResult, run_comps
from backend.data_providers.fred_client import fetch_risk_free_rate
from backend.data_providers.yfinance_client import fetch_enriched_fundamentals as fetch_fundamentals
from backend.news.engine import NewsSentiment, analyze_news
from backend.nlp.models import RiskOutput
from backend.nlp.risk_analyzer import analyze_risk
from backend.technicals.engine import TechnicalSnapshot, compute_technicals
from backend.valuation.aggregator import BlendedTarget, build_blended_target
from backend.valuation.auditor import audit, auditor_passes
from backend.valuation.dcf import run_dcf
from backend.valuation.derivation import derive_assumptions
from backend.valuation.football_field import FootballField, build_football_field
from backend.valuation.gap_analysis import ValuationGapAnalysis, build_gap_analysis
from backend.valuation.models import Assumptions, AuditFinding, DCFResult, SensitivityTable
from backend.valuation.monte_carlo import MonteCarloResult, run_monte_carlo
from backend.valuation.scenarios import ScenarioBundle, run_scenarios
from backend.valuation.sensitivity import sensitivity_table


class ValuationBundle(BaseModel):
    model_config = ConfigDict(frozen=True)
    dcf: DCFResult
    sensitivity: SensitivityTable
    monte_carlo: MonteCarloResult | None
    audit: list[AuditFinding]
    auditor_ok: bool
    provenance: dict[str, str] = {}
    scenarios: ScenarioBundle | None = None
    comps: CompsResult | None = None
    technicals: TechnicalSnapshot | None = None
    news: NewsSentiment | None = None
    football_field: FootballField | None = None
    blended_target: BlendedTarget | None = None
    gap_analysis: ValuationGapAnalysis | None = None


async def valuate(
    ticker: str,
    assumptions: Assumptions | None = None,
    include_monte_carlo: bool = False,
    include_overlays: bool = True,
) -> ValuationBundle:
    from backend.valuation.beta import compute_beta
    import dataclasses

    f = await fetch_fundamentals(ticker)
    rfr = await fetch_risk_free_rate()

    # Replace spot beta with our Blume-adjusted 2Y weekly beta (free, more stable)
    blume_beta = await compute_beta(ticker, fallback=f.beta)
    f = f.model_copy(update={"beta": blume_beta})

    findings = audit(f)
    if not auditor_passes(findings):
        raise ValueError(
            f"auditor blocked valuation for {ticker}: "
            + "; ".join(x.detail for x in findings if not x.ok)
        )

    comps = await run_comps(ticker) if include_overlays else None
    peer_ev_ebitda = comps.median_ev_ebitda if comps else None

    provenance: dict[str, str] = {}
    if assumptions is None:
        derived = await derive_assumptions(f, peer_ev_ebitda=peer_ev_ebitda)
        assumptions = derived.assumptions
        provenance = derived.provenance
    else:
        provenance = {"note": "user-supplied assumptions override; no derivation used"}

    dcf = run_dcf(f, risk_free_rate=rfr.rate, assumptions=assumptions)
    sens = sensitivity_table(f, base=dcf.assumptions, risk_free_rate=rfr.rate)
    mc = (
        run_monte_carlo(f, base=dcf.assumptions, risk_free_rate=rfr.rate, iterations=2_000)
        if include_monte_carlo
        else None
    )

    scenarios: ScenarioBundle | None = None
    technicals: TechnicalSnapshot | None = None
    news: NewsSentiment | None = None
    risk: RiskOutput | None = None
    football: FootballField | None = None
    if include_overlays:
        try:
            scenarios = await run_scenarios(ticker, peer_ev_ebitda=peer_ev_ebitda)
        except Exception:
            scenarios = None
        try:
            technicals = await compute_technicals(ticker)
        except Exception:
            technicals = None
        try:
            news = await analyze_news(ticker)
        except Exception:
            news = None
        try:
            risk = await analyze_risk(ticker)
        except Exception:
            risk = None
        football = build_football_field(dcf.current_price, scenarios, comps, technicals)

    blended: BlendedTarget | None = None
    if include_overlays:
        blended = await build_blended_target(
            scenarios=scenarios,
            comps=comps,
            technicals=technicals,
            risk=risk,
            current_price=dcf.current_price,
            provenance=provenance,
            fundamentals=f,
            ticker=ticker,
        )

    gap_analysis: ValuationGapAnalysis | None = None
    if include_overlays:
        gap_analysis = build_gap_analysis(
            fundamentals=f,
            dcf=dcf,
            blended=blended,
            comps=comps,
            technicals=technicals,
            news=news,
            risk=risk,
        )

    return ValuationBundle(
        dcf=dcf,
        sensitivity=sens,
        monte_carlo=mc,
        audit=findings,
        auditor_ok=True,
        provenance=provenance,
        scenarios=scenarios,
        comps=comps,
        technicals=technicals,
        news=news,
        football_field=football,
        blended_target=blended,
        gap_analysis=gap_analysis,
    )
