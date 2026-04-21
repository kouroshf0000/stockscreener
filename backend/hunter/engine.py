from __future__ import annotations

import asyncio
import statistics
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from backend.comps.engine import run_comps
from backend.data_providers.yfinance_client import fetch_fundamentals
from backend.exports.pdf_memo import build_pdf
from backend.exports.xlsx_writer import build_xlsx
from backend.hunter.gate import run_gate
from backend.hunter.ledger import save_run
from backend.hunter.models import HunterPick, HunterRunReport, ScoutScore
from backend.hunter.scouts import (
    score_catalyst,
    score_catalyst_async,
    score_momentum,
    score_quality,
    score_value,
)
from backend.nlp.risk_analyzer import analyze_risk
from backend.nlp.thesis_writer import generate_thesis_narrative
from backend.screener.metrics import pe_ratio
from backend.screener.universe import universe_for
from backend.valuation.engine import valuate

EXPORT_DIR = Path("exports")
SCOUT_WEIGHTS: dict[str, Decimal] = {
    "value": Decimal("0.30"),
    "quality": Decimal("0.30"),
    "momentum": Decimal("0.20"),
    "catalyst": Decimal("0.20"),
}


async def _sector_median_pe(symbols: list[str]) -> dict[str, Decimal]:
    async def _row(sym: str) -> tuple[str, Decimal | None, str | None]:
        try:
            f = await fetch_fundamentals(sym)
        except Exception:
            return sym, None, None
        return sym, pe_ratio(f), f.sector

    rows = await asyncio.gather(*(_row(s) for s in symbols))
    buckets: dict[str, list[float]] = {}
    for _, pe, sec in rows:
        if pe is not None and sec:
            buckets.setdefault(sec, []).append(float(pe))
    return {
        sec: Decimal(str(round(statistics.median(vals), 4)))
        for sec, vals in buckets.items()
        if vals
    }


def _composite(scores: list[ScoutScore]) -> Decimal:
    total = Decimal(0)
    for s in scores:
        total += s.score * SCOUT_WEIGHTS[s.scout]
    return total


def _thesis_bullets(
    ticker: str, scores: list[ScoutScore], val_upside: Decimal | None
) -> list[str]:
    bullets: list[str] = []
    top = sorted(scores, key=lambda s: s.score, reverse=True)
    for s in top[:2]:
        if s.evidence:
            bullets.append(f"{s.scout.title()}: {s.evidence[0]}")
    if val_upside is not None and val_upside > 0:
        bullets.append(f"DCF implies {float(val_upside) * 100:.0f}% upside vs current price.")
    return bullets


async def _evaluate(sym: str, sector_medians: dict[str, Decimal]) -> HunterPick | None:
    try:
        f = await fetch_fundamentals(sym)
    except Exception:
        return None

    sec_med = sector_medians.get(f.sector or "")
    v_scout = score_value(f, sec_med)
    q_scout = score_quality(f)
    m_scout = score_momentum(f)

    risk = await analyze_risk(sym)
    total_risk = (
        risk.assessment.legal_risk
        + risk.assessment.regulatory_risk
        + risk.assessment.macro_risk
        + risk.assessment.competitive_risk
    )
    cusip: str | None = getattr(f, "cusip", None)
    c_scout = await score_catalyst_async(f, risk_level_total=total_risk, cusip=cusip)

    scores = [v_scout, q_scout, m_scout, c_scout]
    composite = _composite(scores)

    try:
        val = await valuate(sym)
    except Exception:
        return HunterPick(
            ticker=sym,
            pick_date=date.today(),
            pick_price=f.price,
            target_price=None,
            upside_pct=None,
            composite_score=composite,
            scout_scores=scores,
            gate_checks=[],
            gate_passed=False,
            thesis_bullets=[],
        )
    comps = await run_comps(sym)

    passed, checks = run_gate(
        val, comps, f.market_cap, legal_risk=risk.assessment.legal_risk
    )

    return HunterPick(
        ticker=sym,
        pick_date=date.today(),
        pick_price=val.dcf.current_price,
        target_price=val.dcf.implied_share_price,
        upside_pct=val.dcf.upside_pct,
        composite_score=composite,
        scout_scores=scores,
        gate_checks=checks,
        gate_passed=passed,
        thesis_bullets=_thesis_bullets(sym, scores, val.dcf.upside_pct),
    )


async def _emit_deliverables(pick: HunterPick) -> HunterPick:
    try:
        val = await valuate(pick.ticker)
        comps = await run_comps(pick.ticker)
        risk = await analyze_risk(pick.ticker)
    except Exception:
        return pick
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = pick.pick_date.isoformat()
    xlsx_path = EXPORT_DIR / f"{pick.ticker}_{stamp}.xlsx"
    pdf_path = EXPORT_DIR / f"{pick.ticker}_memo_{stamp}.pdf"
    build_xlsx(xlsx_path, val, comps, risk)
    narrative = await generate_thesis_narrative(val, comps, risk)
    scout_ctx = {
        "composite_score": str(pick.composite_score),
        "scouts_fired": [s.scout for s in pick.scout_scores if s.score >= Decimal("60")],
        "narrative": narrative,
    }
    build_pdf(pdf_path, val, comps, risk, scout_context=scout_ctx)
    return pick.model_copy(
        update={"deliverables": {"xlsx": str(xlsx_path), "pdf": str(pdf_path)}}
    )


async def run_hunt(
    universe_name: str = "SP500",
    top_n: int = 5,
    limit: int | None = None,
) -> HunterRunReport:
    started = datetime.now()
    symbols = list(universe_for(universe_name))
    if limit:
        symbols = symbols[:limit]

    medians = await _sector_median_pe(symbols)
    evaluated = await asyncio.gather(*(_evaluate(s, medians) for s in symbols))
    picks = [p for p in evaluated if p is not None]
    picks.sort(key=lambda p: p.composite_score, reverse=True)

    passed = [p for p in picks if p.gate_passed][:top_n]
    rejected = [p for p in picks if not p.gate_passed][:top_n]

    enriched = await asyncio.gather(*(_emit_deliverables(p) for p in passed))

    report = HunterRunReport(
        run_id=uuid.uuid4().hex[:12],
        started_at=started,
        finished_at=datetime.now(),
        candidates_evaluated=len(picks),
        picks=list(enriched),
        rejected=rejected,
    )
    save_run(report)
    return report
