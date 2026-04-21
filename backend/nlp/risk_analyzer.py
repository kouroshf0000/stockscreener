from __future__ import annotations

import json
import logging
from datetime import date
from decimal import Decimal

from anthropic import AsyncAnthropic

from backend.app.cache import get_redis
from backend.app.config import get_settings
from backend.data_providers.cache import key

logger = logging.getLogger(__name__)
from backend.data_providers.edgar_client import fetch_risk_factors_cached_with_diagnostics
from backend.nlp.models import RiskAssessment, RiskOutput
from backend.nlp.persona import RISK_ANALYST_SYSTEM

MAX_ADJUSTMENT = Decimal("0.02")
PER_LEVEL_BPS = Decimal("0.0033")

SYSTEM_PROMPT = RISK_ANALYST_SYSTEM


def _adjustment_from(a: RiskAssessment) -> Decimal:
    total = a.legal_risk + a.regulatory_risk + a.macro_risk + a.competitive_risk
    adj = Decimal(total) * PER_LEVEL_BPS
    return min(adj, MAX_ADJUSTMENT)


def _neutral_assessment(msg: str) -> RiskAssessment:
    return RiskAssessment(
        legal_risk=1,
        regulatory_risk=1,
        macro_risk=1,
        competitive_risk=1,
        summary=msg,
        top_risks=[],
    )


def _fallback(ticker: str, reason: str, filing_info: dict | None = None) -> RiskOutput:
    readable = {
        "no_anthropic_api_key": "No ANTHROPIC_API_KEY configured — running without LLM.",
        "no_10k_filing_found_on_edgar": "No 10-K / 10-K/A / 20-F filing found on SEC EDGAR.",
        "primary_doc_fetch_failed": "SEC primary document fetch failed.",
        "primary_doc_too_small_likely_cover_page": "SEC returned a cover page, not the 10-K body.",
        "risk_factors_section_not_found_in_primary_doc": (
            "Risk Factors section not found in the 10-K primary document "
            "(likely a non-standard format or split-exhibit filing)."
        ),
        "cached_empty": "Previous attempt returned no text; cached empty result.",
        "haiku_call_failed": "Claude Haiku API call failed.",
        "no_valid_json_from_haiku": "Haiku response did not contain valid JSON.",
    }
    base = readable.get(reason.split(":")[0], reason)
    summary = f"Fallback: {base}"
    a = _neutral_assessment(summary)
    info = filing_info or {}
    return RiskOutput(
        ticker=ticker.upper(),
        assessment=a,
        discount_rate_adjustment=_adjustment_from(a),
        source="fallback",
        fallback_reason=reason,
        filing_accession=info.get("accession"),
        filing_form=info.get("form"),
        filing_date=info.get("filed"),
        filing_url=info.get("url"),
        risk_factors_chars=0,
    )


async def _call_haiku(text: str) -> RiskAssessment:
    settings = get_settings()
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    resp = await client.messages.create(
        model=settings.risk_model,
        max_tokens=800,
        temperature=0,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": text[:60_000]}],
    )
    chunks = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
    raw = "".join(chunks).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON found in response")
    data = json.loads(raw[start : end + 1])
    return RiskAssessment.model_validate(data)


async def analyze_risk(ticker: str, include_quarterly: bool = False) -> RiskOutput:
    settings = get_settings()
    sym = ticker.upper()
    r = get_redis()
    suffix = "qq" if include_quarterly else "aq"
    cache_key = key("haiku", "risk", sym, suffix, date.today().isoformat())

    try:
        cached = await r.get(cache_key)
        if cached:
            return RiskOutput.model_validate_json(cached)
    except Exception:
        logger.debug("Redis unavailable for GET risk:%s — continuing without cache", sym)

    async def _cache_set(out: RiskOutput) -> None:
        try:
            await r.set(cache_key, out.model_dump_json(), ex=settings.cache_ttl_haiku_s)
        except Exception:
            logger.debug("Redis unavailable for SET risk:%s", sym)

    if not settings.anthropic_api_key:
        out = _fallback(sym, "no_anthropic_api_key")
        await _cache_set(out)
        return out

    from backend.filings.risk_factors import fetch_risk_factors_universal

    trace = await fetch_risk_factors_universal(sym, include_quarterly=include_quarterly)
    extract_text = trace.text
    extract_reason = trace.reason
    extract_filing = trace.filing
    filing_info: dict | None = None
    if extract_filing is not None:
        filing_info = {
            "accession": extract_filing.accession,
            "form": extract_filing.form,
            "filed": extract_filing.filed.isoformat(),
            "url": extract_filing.primary_doc_url,
        }

    if extract_text is None:
        out = _fallback(sym, extract_reason, filing_info)
        await _cache_set(out)
        return out

    try:
        assessment = await _call_haiku(extract_text)
    except ValueError:
        out = _fallback(sym, "no_valid_json_from_haiku", filing_info)
        await _cache_set(out)
        return out
    except Exception:
        out = _fallback(sym, "haiku_call_failed", filing_info)
        await _cache_set(out)
        return out

    out = RiskOutput(
        ticker=sym,
        assessment=assessment,
        discount_rate_adjustment=_adjustment_from(assessment),
        source="haiku",
        fallback_reason=None,
        filing_accession=filing_info["accession"] if filing_info else None,
        filing_form=filing_info["form"] if filing_info else None,
        filing_date=filing_info["filed"] if filing_info else None,
        filing_url=filing_info["url"] if filing_info else None,
        risk_factors_chars=len(extract_text),
    )
    await _cache_set(out)
    return out
