from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal, getcontext
from typing import NamedTuple

import yfinance as yf

from backend.app.cache import get_redis
from backend.app.config import get_settings
from backend.data_providers.cache import key
from backend.data_providers.fred_client import fetch_risk_free_rate
from backend.data_providers.models import FinancialStatement, Fundamentals
from backend.valuation.models import Assumptions
from backend.valuation.sector_profiles import SectorProfile, get_profile

getcontext().prec = 28

# Module-level GDP cache — one FRED call per day
_gdp_cache: tuple[Decimal, date] | None = None

DERIVE_WINDOW = 4
EXPLICIT_YEARS = 10
HIGH_GROWTH_YEARS = 5

MIN_TAX = Decimal("0.10")
MAX_TAX = Decimal("0.40")
MIN_MARGIN = Decimal("0.01")
MAX_MARGIN = Decimal("0.60")
DEFAULT_ERP_FALLBACK = Decimal("0.055")


class DerivedAssumptions(NamedTuple):
    assumptions: Assumptions
    provenance: dict[str, str]


def _avg(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values) / Decimal(len(values))


def _clamp(v: Decimal, lo: Decimal, hi: Decimal) -> Decimal:
    return max(lo, min(hi, v))


def _blend(data: Decimal | None, prior: Decimal, weight_prior: float = 0.25) -> Decimal:
    """
    Bayesian-style blend: pull data-derived value toward sector prior
    when data is available, fall back to prior when it's not.
    weight_prior=0.25 means 75% data, 25% prior.
    """
    if data is None:
        return prior
    wp = Decimal(str(weight_prior))
    wd = Decimal(str(1 - weight_prior))
    return wd * data + wp * prior


def _revenue_cagr(statements: list[FinancialStatement], years: int = 3) -> Decimal | None:
    if len(statements) < years + 1:
        return None
    recent = statements[0].revenue
    old = statements[years].revenue
    if recent is None or old is None or old <= 0 or recent <= 0:
        return None
    ratio = float(recent) / float(old)
    if ratio <= 0:
        return None
    cagr = ratio ** (1 / years) - 1
    return Decimal(str(round(cagr, 6)))


def _xbrl_cagr(history: dict[int, Decimal], years: int) -> Decimal | None:
    """Compute revenue CAGR from SEC XBRL 10-year history dict {year: revenue}."""
    if len(history) < years + 1:
        return None
    sorted_years = sorted(history.keys(), reverse=True)
    if len(sorted_years) < years + 1:
        return None
    recent_rev = history[sorted_years[0]]
    old_rev = history[sorted_years[years]]
    if recent_rev <= 0 or old_rev <= 0:
        return None
    ratio = float(recent_rev) / float(old_rev)
    if ratio <= 0:
        return None
    cagr = ratio ** (1 / years) - 1
    return Decimal(str(round(cagr, 6)))


def _avg_ratio(
    statements: list[FinancialStatement],
    num: str,
    den: str = "revenue",
    absolute_num: bool = False,
) -> Decimal | None:
    ratios: list[Decimal] = []
    for s in statements[:DERIVE_WINDOW]:
        numerator = getattr(s, num, None)
        denominator = getattr(s, den, None)
        if numerator is None or denominator is None or denominator <= 0:
            continue
        if absolute_num:
            numerator = abs(numerator)
        ratios.append(numerator / denominator)
    return _avg(ratios)


def _ebit_margin(statements: list[FinancialStatement]) -> Decimal | None:
    r = _avg_ratio(statements, "operating_income")
    return _clamp(r, MIN_MARGIN, MAX_MARGIN) if r is not None else None


def _effective_tax(statements: list[FinancialStatement]) -> Decimal | None:
    rates: list[Decimal] = []
    for s in statements[:DERIVE_WINDOW]:
        if s.tax_rate is not None and Decimal(0) < s.tax_rate < Decimal(1):
            rates.append(s.tax_rate)
    avg = _avg(rates)
    return _clamp(avg, MIN_TAX, MAX_TAX) if avg is not None else None


def _reinvestment_rate_from_components(
    statements: list[FinancialStatement],
    tax_rate: Decimal,
    profile: SectorProfile,
) -> Decimal | None:
    """
    IB-standard reinvestment: (Net Capex + ΔNWC) / NOPAT, 4Y average.
    Net Capex = Gross Capex - D&A (maintenance capex is covered by D&A).
    ΔNWC is the cash outflow from working capital changes (signed).
    SBC excluded — it is already deducted in operating income.
    Data-derived rate is blended with the sector prior.
    """
    rates: list[Decimal] = []
    for s in statements[:DERIVE_WINDOW]:
        if s.operating_income is None or s.operating_income <= 0:
            continue
        nopat = s.operating_income * (Decimal(1) - tax_rate)
        if nopat <= 0:
            continue
        gross_capex = abs(s.capex) if s.capex is not None else Decimal(0)
        da = s.depreciation_and_amortization or Decimal(0)
        net_capex = max(Decimal(0), gross_capex - da)
        # yfinance CF sign: positive = NWC released cash (NWC decreased).
        # Reinvestment = cash consumed by NWC → nwc_reinv = -nwc_change when < 0.
        nwc_change = s.working_capital_change or Decimal(0)
        nwc_reinv = max(Decimal(0), -nwc_change)
        reinv = (net_capex + nwc_reinv) / nopat
        rates.append(reinv)

    data_rate = _avg(rates)
    blended = _blend(data_rate, profile.reinv_prior, weight_prior=0.20)
    return _clamp(blended, profile.reinv_floor, profile.reinv_ceiling)


def _two_stage_growth(
    high: Decimal,
    terminal: Decimal,
    high_years: int = HIGH_GROWTH_YEARS,
    total_years: int = EXPLICIT_YEARS,
) -> list[Decimal]:
    """Stage 1: flat at 'high' for high_years. Stage 2: linear fade to terminal."""
    high = _clamp(high, Decimal("-0.20"), Decimal("0.50"))
    fade_years = total_years - high_years
    out: list[Decimal] = [high] * high_years
    if fade_years <= 0:
        return out[:total_years]
    step = (high - terminal) / Decimal(fade_years)
    for i in range(1, fade_years + 1):
        out.append(Decimal(str(round(float(high - step * Decimal(i)), 6))))
    return out


def _margin_path(
    current_margin: Decimal,
    terminal_margin: Decimal,
    years: int = EXPLICIT_YEARS,
) -> list[Decimal]:
    """Fade current margin toward sector-sustainable margin by terminal year."""
    step = (current_margin - terminal_margin) / Decimal(years)
    return [
        Decimal(str(round(float(current_margin - step * Decimal(i)), 6)))
        for i in range(1, years + 1)
    ]


async def _spx_earnings_yield() -> Decimal | None:
    r = get_redis()
    cache_key = key("spx", "earnings_yield")
    try:
        cached = await r.get(cache_key)
        if cached:
            try:
                return Decimal(cached)
            except Exception:
                pass
    except Exception:
        pass

    def _fetch() -> Decimal | None:
        try:
            t = yf.Ticker("SPY")
            info = getattr(t, "info", {}) or {}
            pe = info.get("trailingPE") or info.get("forwardPE")
            if pe is None or pe <= 0:
                return None
            return Decimal(str(round(1.0 / float(pe), 6)))
        except Exception:
            return None

    ey = await asyncio.to_thread(_fetch)
    if ey is not None:
        try:
            await r.set(cache_key, str(ey), ex=get_settings().cache_ttl_fundamentals_s)
        except Exception:
            pass
    return ey


async def _long_run_nominal_gdp() -> Decimal:
    global _gdp_cache
    today = date.today()
    if _gdp_cache is not None and _gdp_cache[1] == today:
        return _gdp_cache[0]

    settings = get_settings()
    if not settings.fred_api_key:
        return Decimal("0.04")
    import httpx

    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": "GDP",
        "api_key": settings.fred_api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 40,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception:
        return Decimal("0.04")
    obs = [o for o in data.get("observations", []) if o.get("value") not in (None, ".")]
    if len(obs) < 20:
        return Decimal("0.04")
    recent = float(obs[0]["value"])
    old = float(obs[-1]["value"])
    years = (len(obs) - 1) / 4.0
    if old <= 0 or years <= 0:
        return Decimal("0.04")
    cagr = (recent / old) ** (1.0 / years) - 1.0
    result = Decimal(str(round(max(0.02, min(cagr, 0.06)), 4)))
    _gdp_cache = (result, today)
    return result


async def derive_assumptions(
    f: Fundamentals,
    peer_ev_ebitda: Decimal | None = None,
) -> DerivedAssumptions:
    profile = get_profile(f.sector)

    rfr = await fetch_risk_free_rate()
    r_f = rfr.rate

    gdp = await _long_run_nominal_gdp()
    # Terminal growth: min of rfr and long-run GDP, further bounded by sector prior
    terminal_raw = min(r_f, gdp)
    terminal = _clamp(terminal_raw, Decimal("0.01"), profile.terminal_growth_prior + Decimal("0.01"))

    ey = await _spx_earnings_yield()
    if ey is not None and ey > r_f:
        # Damodaran: implied US ERP rarely leaves the 4–6.5% band
        erp = _clamp(ey - r_f, Decimal("0.04"), Decimal("0.065"))
    else:
        erp = DEFAULT_ERP_FALLBACK

    # Tax rate: data-derived, blended with sector floor
    effective_tax = _effective_tax(f.statements)
    marginal_tax = _clamp(
        effective_tax if effective_tax is not None else profile.tax_floor,
        profile.tax_floor,
        MAX_TAX,
    )

    # EBIT margin: prefer TTM from yfinance info (more current than 4Y statement avg).
    # Blend with statement-derived average and sector prior.
    raw_margin = _ebit_margin(f.statements)
    ttm_margin = f.operating_margin  # direct from yfinance info
    if ttm_margin is not None and raw_margin is not None:
        # 55% TTM actual, 45% multi-year average — captures recent margin shift
        blended_margin = ttm_margin * Decimal("0.55") + raw_margin * Decimal("0.45")
    else:
        blended_margin = ttm_margin if ttm_margin is not None else raw_margin
    current_margin = _blend(blended_margin, profile.margin_prior, weight_prior=0.15)
    current_margin = _clamp(current_margin, profile.margin_floor, profile.margin_ceiling)

    # Terminal margin: data-derived companies don't mean-revert to commodity margins.
    # High-margin businesses (software) sustain margins; we allow up to the sector ceiling.
    sector_terminal_margin = _clamp(
        current_margin,
        profile.margin_floor,
        profile.margin_ceiling,
    )

    reinv = _reinvestment_rate_from_components(f.statements, marginal_tax, profile)

    # Historical CAGR: prefer SEC XBRL 10Y history (more years = more stable signal).
    # Fall back to yfinance statements (4Y) if XBRL unavailable.
    hist_cagr = (
        _xbrl_cagr(f.xbrl_revenue_10y, years=5)
        or _xbrl_cagr(f.xbrl_revenue_10y, years=3)
        or _revenue_cagr(f.statements, years=3)
        or _revenue_cagr(f.statements, years=2)
    )

    # Sustainable growth rate = ROE × retention ratio (free, Modigliani-Miller).
    # Use as a cross-check / blend when historical CAGR is unavailable or extreme.
    sgr: Decimal | None = None
    if f.statements:
        s0 = f.statements[0]
        ni = s0.net_income
        eq = s0.total_equity
        fcf = s0.free_cash_flow
        if ni and eq and eq > 0 and ni > 0:
            roe = ni / eq
            retention = Decimal("0.70")
            if fcf is not None and ni > 0:
                retention = _clamp(fcf / ni, Decimal("0.30"), Decimal("0.90"))
            sgr = _clamp(roe * retention, Decimal("0.01"), Decimal("0.40"))

    if hist_cagr is None:
        hist_cagr = sgr if sgr is not None else terminal
    elif sgr is not None:
        hist_cagr = hist_cagr * Decimal("0.70") + sgr * Decimal("0.30")

    fmp_growth = f.analyst_revenue_growth_next_y
    fmp_path = f.analyst_revenue_growth_path  # list of Y1-Y5 consensus growth rates
    recent_growth = f.revenue_growth  # trailing YoY from yfinance (backward-looking)

    # Price-target nudge using FMP consensus target (preferred) or yfinance mean
    analyst_growth_nudge: Decimal | None = None
    target_price = f.fmp_target_consensus or f.analyst_target_mean
    if (
        target_price is not None
        and f.price is not None and f.price > 0
        and f.analyst_count is not None and f.analyst_count >= 3
    ):
        implied_return = (float(target_price) / float(f.price)) - 1.0
        analyst_growth_nudge = Decimal(str(round(max(-0.20, min(0.50, implied_return * 0.3)), 6)))

    if fmp_path and len(fmp_path) >= 3:
        # BEST CASE: FMP gives us the full Y1-Y5 sell-side revenue consensus path.
        # Use it directly — this is exactly what Goldman/JPM anchors to.
        clamped = [_clamp(g, Decimal("-0.20"), Decimal("0.50")) for g in fmp_path[:HIGH_GROWTH_YEARS]]
        while len(clamped) < HIGH_GROWTH_YEARS:
            clamped.append(clamped[-1])
        # Y6-Y10: fade from last consensus year to terminal
        fade_years = EXPLICIT_YEARS - HIGH_GROWTH_YEARS
        last = clamped[-1]
        step = (last - terminal) / Decimal(fade_years) if fade_years > 0 else Decimal("0")
        growth = list(clamped)
        for i in range(1, fade_years + 1):
            growth.append(Decimal(str(round(float(last - step * Decimal(i)), 6))))
        hist_cagr = clamped[0]  # for provenance logging
    else:
        # FALLBACK: blend historical CAGR + TTM momentum + optional FMP Y1
        if fmp_growth is not None and hist_cagr is not None:
            ttm_weight = Decimal("0.15") if recent_growth is not None else Decimal("0")
            ttm_contrib = (recent_growth or Decimal("0")) * ttm_weight
            hist_cagr = fmp_growth * Decimal("0.50") + hist_cagr * (Decimal("0.50") - ttm_weight) + ttm_contrib
        elif recent_growth is not None and hist_cagr is not None:
            hist_cagr = hist_cagr * Decimal("0.60") + recent_growth * Decimal("0.40")
        elif fmp_growth is not None:
            hist_cagr = fmp_growth
        elif recent_growth is not None:
            hist_cagr = recent_growth
        # Apply analyst price-target nudge
        if analyst_growth_nudge is not None and hist_cagr is not None:
            hist_cagr = hist_cagr * Decimal("0.85") + analyst_growth_nudge * Decimal("0.15")
        growth = _two_stage_growth(hist_cagr, terminal, HIGH_GROWTH_YEARS, EXPLICIT_YEARS)
    margin_path = _margin_path(current_margin, sector_terminal_margin, EXPLICIT_YEARS)

    # Use sector-typical EV/EBITDA as exit multiple fallback when no peer data
    exit_multiple = peer_ev_ebitda or profile.ev_ebitda_typical

    assumptions = Assumptions(
        revenue_growth=growth,
        ebit_margin=current_margin,
        ebit_margin_path=margin_path,
        tax_rate=marginal_tax,
        reinvestment_rate=reinv,
        terminal_growth=terminal,
        equity_risk_premium=erp,
        exit_multiple_ev_ebitda=exit_multiple,
    )

    capex_pct = _avg_ratio(f.statements, "capex", absolute_num=True)
    nwc_pct = _avg_ratio(f.statements, "working_capital_change", absolute_num=True)
    da_pct = _avg_ratio(f.statements, "depreciation_and_amortization", absolute_num=True)

    provenance = {
        "sector": f"{f.sector or 'unknown'} → profile applied",
        "revenue_growth": (
            f"2-stage: {HIGH_GROWTH_YEARS}Y flat at {hist_cagr:.1%} "
            f"(60% hist CAGR, 40% TTM {recent_growth:.1%}"
            + (f", SGR={sgr:.1%}" if sgr else "")
            + (f", analyst nudge={analyst_growth_nudge:.1%} [{f.analyst_count} analysts, target ${float(f.analyst_target_mean):.0f}]" if analyst_growth_nudge is not None else "")
            + f"), fade to terminal ({terminal:.1%})"
            if recent_growth is not None else
            f"2-stage: {HIGH_GROWTH_YEARS}Y flat at {hist_cagr:.1%} "
            + (f"(70% hist CAGR, 30% SGR={sgr:.1%})" if sgr else "(hist CAGR)")
            + f", fade to terminal ({terminal:.1%})"
        ),
        "ebit_margin_path": (
            f"current {current_margin:.1%} (data-blended with sector prior {profile.margin_prior:.1%}), "
            f"fade to {sector_terminal_margin:.1%} by Y{EXPLICIT_YEARS}"
        ),
        "tax_rate": (
            f"effective {effective_tax:.1%} → clamped to sector floor {profile.tax_floor:.1%}"
            if effective_tax else f"sector floor {profile.tax_floor:.1%} (no data)"
        ),
        "reinvestment_rate": (
            f"net capex/NOPAT blended with {profile.sector_label if hasattr(profile,'sector_label') else 'sector'} "
            f"prior {profile.reinv_prior:.1%} → {reinv:.1%} "
            f"[gross_capex%rev={capex_pct}, da%rev={da_pct}, nwc%rev={nwc_pct}]"
        ),
        "terminal_growth": f"min(10Y Treasury {r_f:.2%}, GDP CAGR {gdp:.2%}) → {terminal:.2%}",
        "equity_risk_premium": (
            f"SPY earnings yield minus rfr → {erp:.2%}"
            if ey else f"fallback {DEFAULT_ERP_FALLBACK:.2%} (SPY data unavailable)"
        ),
        "exit_multiple_ev_ebitda": (
            f"peer median {peer_ev_ebitda}x (from comps)"
            if peer_ev_ebitda else
            f"sector prior {exit_multiple}x (no peer data)"
            if exit_multiple else "not set"
        ),
    }
    return DerivedAssumptions(assumptions=assumptions, provenance=provenance)
