from __future__ import annotations

from datetime import date
from decimal import Decimal, getcontext

from backend.data_providers.models import Fundamentals
from backend.valuation.models import (
    Assumptions,
    DCFResult,
    ProjectionRow,
    WACCBreakdown,
    WACCInputs,
)
from backend.valuation.normalization import base_revenue, latest
from backend.valuation.wacc import compute_wacc, estimate_cost_of_debt

getcontext().prec = 28


def _q(x: Decimal, places: str = "0.0001") -> Decimal:
    return x.quantize(Decimal(places))


def _clamp(v: Decimal, lo: Decimal, hi: Decimal) -> Decimal:
    return max(lo, min(hi, v))


def _red_flags(
    f: Fundamentals,
    projections: list[ProjectionRow],
    assumptions: Assumptions,
) -> list[str]:
    flags: list[str] = []

    if len(f.statements) >= 4:
        rev_growth = []
        fcf_growth = []
        for i in range(3):
            a, b = f.statements[i], f.statements[i + 1]
            if a.revenue and b.revenue and b.revenue > 0:
                rev_growth.append(float(a.revenue) / float(b.revenue) - 1)
            if a.free_cash_flow and b.free_cash_flow and b.free_cash_flow > 0:
                fcf_growth.append(float(a.free_cash_flow) / float(b.free_cash_flow) - 1)
        if (
            len(rev_growth) >= 3
            and len(fcf_growth) >= 3
            and all(fg > rg for fg, rg in zip(fcf_growth, rev_growth, strict=False))
        ):
            flags.append(
                "FCF growth outpaced revenue growth for 3 consecutive years — "
                "margin expansion of this magnitude is historically rare."
            )

    if assumptions.terminal_growth >= Decimal("0.05"):
        flags.append(
            "Terminal growth >= 5% is above long-run GDP — perpetuity assumption may be aggressive."
        )

    return flags


def run_dcf(
    f: Fundamentals,
    risk_free_rate: Decimal,
    assumptions: Assumptions | None = None,
    current_price: Decimal | None = None,
) -> DCFResult:
    assumptions = assumptions or Assumptions()
    s = latest(f)
    if s is None:
        raise ValueError("no statements available")

    rev0 = base_revenue(f)
    if rev0 is None:
        raise ValueError("no positive revenue anchor")

    from backend.valuation.sector_profiles import get_profile as _get_profile
    _prof = _get_profile(f.sector)
    raw_beta = f.beta or Decimal("1.0")
    # Sector-clamp the yfinance spot beta; caller should pre-compute Blume beta
    # via beta.compute_beta() and pass it in as f.beta for best accuracy.
    beta = _clamp(raw_beta, _prof.beta_floor, _prof.beta_ceiling)
    market_cap = f.market_cap or Decimal(0)
    debt = s.total_debt or Decimal(0)
    cash = s.cash_and_equivalents or Decimal(0)
    shares = s.shares_outstanding
    if shares is None or shares <= 0:
        if f.price and f.price > 0 and f.market_cap and f.market_cap > 0:
            shares = f.market_cap / f.price
        else:
            raise ValueError("shares outstanding unavailable")

    effective_erp = assumptions.equity_risk_premium + assumptions.risk_premium_adjustment
    wacc_inputs = WACCInputs(
        risk_free_rate=risk_free_rate,
        beta=beta,
        equity_risk_premium=effective_erp,
        cost_of_debt=estimate_cost_of_debt(f),
        tax_rate=assumptions.tax_rate,
        market_cap=market_cap,
        total_debt=debt,
    )
    wacc_b: WACCBreakdown = compute_wacc(wacc_inputs)
    wacc = wacc_b.wacc

    n_years = len(assumptions.revenue_growth)
    margin_path = assumptions.ebit_margin_path or [assumptions.ebit_margin] * n_years
    reinv_path = assumptions.reinvestment_rate_path or [assumptions.reinvestment_rate] * n_years
    if len(margin_path) != n_years or len(reinv_path) != n_years:
        raise ValueError("margin_path and reinvestment_rate_path must match revenue_growth length")

    projections: list[ProjectionRow] = []
    revenue = rev0
    pv_explicit = Decimal(0)
    for i, (g, margin, reinv_rate) in enumerate(
        zip(assumptions.revenue_growth, margin_path, reinv_path, strict=False), start=1
    ):
        revenue = revenue * (Decimal(1) + g)
        ebit = revenue * margin
        nopat = ebit * (Decimal(1) - assumptions.tax_rate)
        reinvestment = nopat * reinv_rate
        fcff = nopat - reinvestment
        df = (Decimal(1) + wacc) ** i
        discount_factor = Decimal(1) / df
        pv = fcff * discount_factor
        pv_explicit += pv
        projections.append(
            ProjectionRow(
                year=i,
                revenue=_q(revenue, "0.01"),
                ebit=_q(ebit, "0.01"),
                nopat=_q(nopat, "0.01"),
                reinvestment=_q(reinvestment, "0.01"),
                fcff=_q(fcff, "0.01"),
                discount_factor=_q(discount_factor, "0.000001"),
                pv_fcff=_q(pv, "0.01"),
            )
        )

    if wacc <= assumptions.terminal_growth:
        raise ValueError(f"WACC ({wacc}) must exceed terminal growth ({assumptions.terminal_growth})")

    terminal_fcff = projections[-1].fcff * (Decimal(1) + assumptions.terminal_growth)
    tv_gordon = terminal_fcff / (wacc - assumptions.terminal_growth)
    tv = tv_gordon
    if assumptions.exit_multiple_ev_ebitda is not None:
        terminal_revenue = projections[-1].revenue * (Decimal(1) + assumptions.terminal_growth)
        terminal_ebit = terminal_revenue * margin_path[-1]
        last_da = (s.ebitda or Decimal(0)) - (s.operating_income or Decimal(0))
        da_ratio = Decimal(0)
        if s.revenue and s.revenue > 0:
            da_ratio = last_da / s.revenue
        terminal_ebitda = terminal_ebit + terminal_revenue * da_ratio
        tv_exit = terminal_ebitda * assumptions.exit_multiple_ev_ebitda
        # IB standard: blend Gordon Growth (60%) with exit multiple (40%) rather than
        # taking the minimum — the minimum systematically discounts premium franchises.
        if tv_exit > 0:
            tv = tv_gordon * Decimal("0.60") + tv_exit * Decimal("0.40")
    last_df = projections[-1].discount_factor
    pv_tv = tv * last_df

    ev = pv_explicit + pv_tv
    net_debt = debt - cash
    equity_value = ev - net_debt
    implied_price = equity_value / shares if shares > 0 else Decimal(0)

    price = current_price or f.price
    upside = None
    if price and price > 0:
        upside = (implied_price - price) / price

    return DCFResult(
        ticker=f.ticker,
        as_of=date.today(),
        wacc=wacc_b,
        assumptions=assumptions,
        projections=projections,
        pv_explicit=_q(pv_explicit, "0.01"),
        terminal_value=_q(tv, "0.01"),
        pv_terminal=_q(pv_tv, "0.01"),
        enterprise_value=_q(ev, "0.01"),
        net_debt=_q(net_debt, "0.01"),
        equity_value=_q(equity_value, "0.01"),
        shares_outstanding=shares,
        implied_share_price=_q(implied_price, "0.0001"),
        current_price=price,
        upside_pct=upside,
        red_flags=_red_flags(f, projections, assumptions),
    )
