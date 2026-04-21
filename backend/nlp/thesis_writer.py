from __future__ import annotations

import json
from datetime import date

from anthropic import AsyncAnthropic

from backend.app.cache import get_redis
from backend.app.config import get_settings
from backend.comps.engine import CompsResult
from backend.data_providers.cache import key
from backend.nlp.models import RiskOutput
from backend.nlp.persona import THESIS_NARRATIVE_SYSTEM
from backend.valuation.engine import ValuationBundle


def _inputs_digest(
    val: ValuationBundle, comps: CompsResult | None, risk: RiskOutput | None
) -> dict[str, object]:
    dcf = val.dcf
    return {
        "ticker": dcf.ticker,
        "current_price": float(dcf.current_price) if dcf.current_price else None,
        "implied_price_dcf": float(dcf.implied_share_price),
        "upside_pct": float(dcf.upside_pct) if dcf.upside_pct is not None else None,
        "wacc": float(dcf.wacc.wacc),
        "cost_of_equity": float(dcf.wacc.cost_of_equity),
        "terminal_growth": float(dcf.assumptions.terminal_growth),
        "ebit_margin": float(dcf.assumptions.ebit_margin),
        "revenue_growth_y1_y5": [float(g) for g in dcf.assumptions.revenue_growth],
        "enterprise_value": float(dcf.enterprise_value),
        "equity_value": float(dcf.equity_value),
        "red_flags": dcf.red_flags,
        "comps_implied_pe": float(comps.implied_price_pe)
        if comps and comps.implied_price_pe
        else None,
        "comps_implied_ev_ebitda": float(comps.implied_price_ev_ebitda)
        if comps and comps.implied_price_ev_ebitda
        else None,
        "peer_symbols": [p.symbol for p in comps.peers] if comps else [],
        "risk_scores": {
            "legal": risk.assessment.legal_risk if risk else None,
            "regulatory": risk.assessment.regulatory_risk if risk else None,
            "macro": risk.assessment.macro_risk if risk else None,
            "competitive": risk.assessment.competitive_risk if risk else None,
        }
        if risk
        else {},
        "risk_summary": risk.assessment.summary if risk else None,
    }


def _fallback_narrative(d: dict[str, object]) -> str:
    ticker = d.get("ticker", "the company")
    up = d.get("upside_pct")
    up_str = f"{float(up) * 100:.0f}%" if isinstance(up, (int, float)) else "n/a"
    wacc = d.get("wacc")
    tg = d.get("terminal_growth")
    return (
        f"Thesis: The model's DCF indicates approximately {up_str} implied upside for {ticker} "
        f"under current assumptions, with comps providing an independent reference range. "
        f"Durability of unit economics and capital allocation track record are the levers most likely "
        f"to determine whether the implied price is achievable.\n\n"
        f"What has to be true: Revenue growth trajectory must track the explicit 5-year path, "
        f"EBIT margin must sustain at modeled levels through competitive pressure, and the "
        f"perpetuity assumption (terminal growth {float(tg) * 100:.2f}%) must remain "
        f"reconcilable with a WACC of {float(wacc) * 100:.2f}%.\n\n"
        f"What would kill the thesis: Margin compression that widens the gap between revenue and FCF, "
        f"a deterioration in the risk profile that widens the cost of equity, or any catalyst that "
        f"invalidates the competitive positioning assumed in the base case. The PM should watch "
        f"quarterly operating-margin trajectory and any change in regulatory posture."
    )


async def generate_thesis_narrative(
    val: ValuationBundle,
    comps: CompsResult | None = None,
    risk: RiskOutput | None = None,
) -> str:
    settings = get_settings()
    digest = _inputs_digest(val, comps, risk)
    ticker = val.dcf.ticker

    r = get_redis()
    cache_key = key("haiku", "thesis", ticker, date.today().isoformat())
    try:
        cached = await r.get(cache_key)
        if cached:
            return cached
    except Exception:
        pass

    if not settings.anthropic_api_key:
        text = _fallback_narrative(digest)
        try:
            await r.set(cache_key, text, ex=settings.cache_ttl_haiku_s)
        except Exception:
            pass
        return text

    try:
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        resp = await client.messages.create(
            model=settings.narrative_model,
            max_tokens=700,
            temperature=0,
            system=[
                {
                    "type": "text",
                    "text": THESIS_NARRATIVE_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": "Structured inputs (JSON):\n" + json.dumps(digest, indent=2),
                }
            ],
        )
        chunks = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        text = "".join(chunks).strip()
        if not text:
            text = _fallback_narrative(digest)
    except Exception:
        text = _fallback_narrative(digest)

    try:
        await r.set(cache_key, text, ex=settings.cache_ttl_haiku_s)
    except Exception:
        pass
    return text
