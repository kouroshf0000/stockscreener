from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Literal

from anthropic import AsyncAnthropic
from pydantic import BaseModel, ConfigDict, Field

from backend.app.config import get_settings
from backend.data_providers.models import Fundamentals
from backend.valuation.models import Assumptions

logger = logging.getLogger(__name__)

# ── Anthropic client (singleton) ──────────────────────────────────────────────

_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    return _client


# ── System prompt (cached — never changes per request) ────────────────────────

_EQUITY_RESEARCHER_SYSTEM = """You are a senior equity research analyst with deep expertise \
in fundamental valuation (DCF, EV/EBITDA, comparable analysis), technical analysis across \
multiple timeframes, and quantitative signal generation.

Your role is to reason carefully about:
1. DCF model assumptions — what revenue growth, margins, reinvestment, and terminal growth \
are defensible given the company's sector, competitive position, historical trajectory, \
and current macro environment.
2. Swing and intraday trade signals — whether a technical setup across multiple timeframes \
represents a high-probability entry, based on trend alignment, momentum, mean-reversion, \
and risk/reward.

You think in first principles. You do not apply generic rules mechanically. \
You reason about what is specific to this company or setup and why. \
Your output is always structured JSON — no prose outside the schema.

Key principles:
- For DCF: assumptions must be internally consistent. High growth demands high reinvestment. \
Mature companies should have margins converging toward sector medians. \
Be conservative — err toward lower growth and higher discount rates rather than optimistic base cases.
- For trade signals: require timeframe alignment. A 1D bullish setup with a 4H downtrend is not a buy. \
Size confidence to conviction — only output HIGH confidence when all evidence aligns.
- Always explain your reasoning per field. A number without a rationale is useless."""


# ── Output models ─────────────────────────────────────────────────────────────

class FieldReasoning(BaseModel):
    value: float
    reasoning: str


class ReasonedAssumptions(BaseModel):
    """Claude-derived DCF assumptions with per-field reasoning."""
    model_config = ConfigDict(frozen=True)

    revenue_growth_y1_y5: list[float] = Field(description="Annual revenue growth rates for years 1-5")
    revenue_growth_y6_y10: list[float] = Field(description="Annual revenue growth rates for years 6-10 (fade)")
    ebit_margin: float = Field(description="Normalised EBIT margin at steady state")
    ebit_margin_reasoning: str
    reinvestment_rate: float = Field(description="Reinvestment as fraction of NOPAT")
    reinvestment_reasoning: str
    terminal_growth: float = Field(description="Perpetuity growth rate post-year-10")
    terminal_growth_reasoning: str
    tax_rate: float
    growth_reasoning: str = Field(description="Why this growth trajectory is appropriate")
    overall_thesis: str = Field(description="2-3 sentence summary of the valuation view")
    confidence: Literal["low", "medium", "high"]


class ReasonedTradeSignal(BaseModel):
    """Claude-derived swing or day trade signal."""
    model_config = ConfigDict(frozen=True)

    direction: Literal["long", "short", "no_trade"]
    strategy_type: Literal["swing", "day", "no_trade"]
    entry_rationale: str
    entry_price_note: str = Field(description="e.g. 'limit near 52w VWAP support at ~$X' or 'no trade'")
    stop_loss_note: str = Field(description="where to cut the position and why")
    target_note: str = Field(description="price target and basis")
    risk_reward_estimate: float = Field(description="estimated R:R ratio, 0 if no_trade")
    stop_loss_pct: float = Field(default=0.0, description="stop loss distance as % from entry (positive number, e.g. 3.0 means 3% below entry for longs). Set 0.0 for no_trade.")
    target_pct: float = Field(default=0.0, description="take profit distance as % from entry (positive number, e.g. 6.0 means 6% above entry for longs). Set 0.0 for no_trade.")
    timeframe_alignment: str = Field(description="whether 1D/4H/1H signals agree or conflict")
    key_risks: list[str]
    confidence: Literal["low", "medium", "high"]
    reasoning: str = Field(description="Full reasoning chain for the decision")


# ── DCF assumption reasoning ───────────────────────────────────────────────────

def _build_dcf_context(
    ticker: str,
    f: Fundamentals,
    sector_prior: dict,
    rfr: float,
) -> str:
    stmts = []
    for s in (f.statements or [])[:5]:
        stmts.append({
            "year": str(s.period_end),
            "revenue_bn": round(float(s.revenue) / 1e9, 2) if s.revenue else None,
            "operating_income_bn": round(float(s.operating_income) / 1e9, 2) if s.operating_income else None,
            "ebit_margin_pct": round(float(s.operating_income / s.revenue) * 100, 1) if s.revenue and s.operating_income and s.revenue > 0 else None,
            "capex_bn": round(float(s.capex) / 1e9, 2) if s.capex else None,
            "da_bn": round(float(s.depreciation_and_amortization) / 1e9, 2) if s.depreciation_and_amortization else None,
            "tax_rate_pct": round(float(s.tax_rate) * 100, 1) if s.tax_rate else None,
        })

    # Analyst target context
    analyst_ctx = None
    if f.analyst_target_mean is not None and f.price is not None and f.price > 0:
        implied_upside = round((float(f.analyst_target_mean) / float(f.price) - 1) * 100, 1)
        analyst_ctx = {
            "consensus_target_mean": round(float(f.analyst_target_mean), 2),
            "consensus_target_high": round(float(f.analyst_target_high), 2) if f.analyst_target_high else None,
            "consensus_target_low": round(float(f.analyst_target_low), 2) if f.analyst_target_low else None,
            "implied_upside_to_mean_pct": implied_upside,
            "analyst_count": f.analyst_count,
            "recommendation_mean": round(float(f.analyst_recommendation), 2) if f.analyst_recommendation else None,
            "recommendation_note": "1=Strong Buy, 2=Buy, 3=Hold, 4=Sell, 5=Strong Sell",
        }

    # Segment breakdown
    segments_ctx = None
    if f.segments:
        total = sum(f.segments.values()) or Decimal("1")
        segments_ctx = {
            seg: {
                "revenue_bn": round(float(rev) / 1e9, 2),
                "pct_of_total": round(float(rev / total) * 100, 1),
            }
            for seg, rev in f.segments.items()
        }

    return json.dumps({
        "ticker": ticker,
        "sector": f.sector or "Unknown",
        "industry": f.industry or "Unknown",
        "market_cap_bn": round(float(f.market_cap) / 1e9, 1) if f.market_cap else None,
        "current_price": round(float(f.price), 2) if f.price else None,
        "revenue_ttm_bn": round(float(f.revenue) / 1e9, 2) if f.revenue else None,
        "ebit_margin_ttm_pct": round(float(f.operating_margin) * 100, 1) if f.operating_margin else None,
        "revenue_growth_yoy_pct": round(float(f.revenue_growth) * 100, 1) if f.revenue_growth else None,
        "pe_ratio_trailing": round(float(f.pe_ratio), 1) if f.pe_ratio else None,
        "pe_ratio_forward": round(float(f.forward_pe), 1) if f.forward_pe else None,
        "forward_eps": round(float(f.forward_eps), 2) if f.forward_eps else None,
        "return_on_equity_pct": round(float(f.return_on_equity) * 100, 1) if f.return_on_equity else None,
        "debt_to_equity": round(float(f.debt_to_equity), 2) if f.debt_to_equity else None,
        "beta": round(float(f.beta), 2) if f.beta else None,
        "analyst_consensus": analyst_ctx,
        "analyst_forward_estimates": {
            "revenue_next_y_bn": round(float(f.analyst_revenue_next_y) / 1e9, 2) if f.analyst_revenue_next_y else None,
            "revenue_next_y_low_bn": round(float(f.analyst_revenue_next_y_low) / 1e9, 2) if f.analyst_revenue_next_y_low else None,
            "revenue_next_y_high_bn": round(float(f.analyst_revenue_next_y_high) / 1e9, 2) if f.analyst_revenue_next_y_high else None,
            "eps_next_y": round(float(f.analyst_eps_next_y), 2) if f.analyst_eps_next_y else None,
            "revenue_growth_next_y_pct": round(float(f.analyst_revenue_growth_next_y) * 100, 1) if f.analyst_revenue_growth_next_y else None,
        },
        "market_signals": {
            "short_pct_float": round(float(f.short_pct_float) * 100, 1) if f.short_pct_float else None,
            "held_pct_institutions": round(float(f.held_pct_institutions) * 100, 1) if f.held_pct_institutions else None,
            "earnings_growth_pct": round(float(f.earnings_growth) * 100, 1) if f.earnings_growth else None,
        },
        "credit_environment": {
            "hy_spread_pct": round(float(f.credit_spread_hy) * 100, 2) if f.credit_spread_hy else None,
            "ig_spread_pct": round(float(f.credit_spread_ig) * 100, 2) if f.credit_spread_ig else None,
        },
        "xbrl_revenue_10y_bn": {
            str(yr): round(float(rev) / 1e9, 2)
            for yr, rev in sorted(f.xbrl_revenue_10y.items(), reverse=True)
        } if f.xbrl_revenue_10y else None,
        "segment_revenue": segments_ctx,
        "historical_statements": stmts,
        "sector_prior": sector_prior,
        "risk_free_rate_pct": round(rfr * 100, 2),
    }, indent=2)


async def reason_dcf_assumptions(
    ticker: str,
    fundamentals: Fundamentals,
    sector_prior: dict,
    rfr: float,
) -> tuple[Assumptions, ReasonedAssumptions]:
    """
    Ask Claude Opus to reason through DCF assumptions from first principles.
    Returns both the structured Assumptions (ready for the DCF engine) and
    the full ReasonedAssumptions with per-field rationale.
    """
    client = _get_client()
    context = _build_dcf_context(ticker, fundamentals, sector_prior, rfr)

    prompt = f"""Analyse the following company data and derive defensible DCF assumptions.
Think carefully about the growth trajectory, margin normalisation, reinvestment intensity, \
and terminal growth rate. Be specific about why each assumption fits THIS company.

<company_data>
{context}
</company_data>

Return a JSON object matching the ReasonedAssumptions schema exactly."""

    response = await client.messages.parse(
        model="claude-opus-4-7",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        system=[{
            "type": "text",
            "text": _EQUITY_RESEARCHER_SYSTEM,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": prompt}],
        output_format=ReasonedAssumptions,
    )

    ra: ReasonedAssumptions = response.parsed_output

    # Build 10-year growth path from Claude's output
    growth_path = [Decimal(str(round(g, 6))) for g in (ra.revenue_growth_y1_y5 + ra.revenue_growth_y6_y10)[:10]]
    while len(growth_path) < 10:
        growth_path.append(growth_path[-1])

    assumptions = Assumptions(
        revenue_growth=growth_path,
        ebit_margin=Decimal(str(round(ra.ebit_margin, 6))),
        tax_rate=Decimal(str(round(ra.tax_rate, 6))),
        reinvestment_rate=Decimal(str(round(ra.reinvestment_rate, 6))),
        terminal_growth=Decimal(str(round(ra.terminal_growth, 6))),
    )

    return assumptions, ra


# ── Trade signal reasoning ─────────────────────────────────────────────────────

def _build_signal_context(
    ticker: str,
    timeframes: dict[str, dict],
    news_sentiment: str | None,
    strategy: Literal["swing", "day"],
) -> str:
    return json.dumps({
        "ticker": ticker,
        "strategy_requested": strategy,
        "timeframes": timeframes,
        "news_sentiment": news_sentiment or "unavailable",
        "note": "Timeframe keys: '1D'=daily, '4H'=4-hour, '1H'=1-hour, '15m'=15-minute",
    }, indent=2)


async def reason_trade_signal(
    ticker: str,
    timeframes: dict[str, dict],
    news_sentiment: str | None = None,
    strategy: Literal["swing", "day"] = "swing",
) -> ReasonedTradeSignal:
    """
    Ask Claude Sonnet to reason through a swing or day trade signal.
    Uses Sonnet (not Opus) to stay within per-run cost budget (~$0.02/call vs ~$0.18).
    timeframes: dict keyed by interval ('1D','4H','1H','15m') → TV indicator dict.
    """
    client = _get_client()
    context = _build_signal_context(ticker, timeframes, news_sentiment, strategy)

    prompt = f"""Analyse the following multi-timeframe technical data for {ticker} and \
determine whether there is a high-probability {strategy} trade setup.

Require timeframe alignment — if higher timeframe trend contradicts the entry timeframe, \
output direction=no_trade unless the conflict has a clear resolution.

<technical_data>
{context}
</technical_data>

Set stop_loss_pct and target_pct as concrete percentage distances from entry price (positive numbers). \
For a long with 3% stop and 6% target: stop_loss_pct=3.0, target_pct=6.0. \
For no_trade set both to 0.0.

Return a JSON object matching the ReasonedTradeSignal schema exactly."""

    response = await client.messages.parse(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=[{
            "type": "text",
            "text": _EQUITY_RESEARCHER_SYSTEM,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": prompt}],
        output_format=ReasonedTradeSignal,
    )

    return response.parsed_output
