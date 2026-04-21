from __future__ import annotations

from decimal import Decimal

from backend.data_providers.models import Fundamentals


def _safe_div(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    if a is None or b is None or b == 0:
        return None
    try:
        return a / b
    except Exception:
        return None


def pe_ratio(f: Fundamentals) -> Decimal | None:
    if not f.statements or f.market_cap is None:
        return None
    ni = f.statements[0].net_income
    return _safe_div(f.market_cap, ni) if ni and ni > 0 else None


def ev_ebitda(f: Fundamentals) -> Decimal | None:
    if not f.statements or f.market_cap is None:
        return None
    s = f.statements[0]
    if s.ebitda is None or s.ebitda <= 0:
        return None
    debt = s.total_debt or Decimal(0)
    cash = s.cash_and_equivalents or Decimal(0)
    ev = f.market_cap + debt - cash
    return _safe_div(ev, s.ebitda)


def fcf_yield(f: Fundamentals) -> Decimal | None:
    if not f.statements or f.market_cap is None:
        return None
    return _safe_div(f.statements[0].free_cash_flow, f.market_cap)


def revenue_cagr_3y(f: Fundamentals) -> Decimal | None:
    if len(f.statements) < 4:
        return None
    recent = f.statements[0].revenue
    old = f.statements[3].revenue
    if recent is None or old is None or old <= 0 or recent <= 0:
        return None
    ratio = float(recent) / float(old)
    if ratio <= 0:
        return None
    cagr = ratio ** (1 / 3) - 1
    return Decimal(str(round(cagr, 6)))


def roic(f: Fundamentals) -> Decimal | None:
    if not f.statements:
        return None
    s = f.statements[0]
    if s.operating_income is None or s.total_equity is None or s.total_debt is None:
        return None
    tax_rate = s.tax_rate if s.tax_rate is not None else Decimal("0.21")
    nopat = s.operating_income * (Decimal(1) - tax_rate)
    invested = s.total_equity + s.total_debt
    return _safe_div(nopat, invested)


def debt_to_equity(f: Fundamentals) -> Decimal | None:
    if not f.statements:
        return None
    s = f.statements[0]
    if s.total_debt is None or s.total_equity is None or s.total_equity <= 0:
        return None
    return _safe_div(s.total_debt, s.total_equity)


def compute_all(f: Fundamentals) -> dict[str, Decimal | None]:
    return {
        "pe_ratio": pe_ratio(f),
        "ev_ebitda": ev_ebitda(f),
        "fcf_yield": fcf_yield(f),
        "revenue_cagr_3y": revenue_cagr_3y(f),
        "roic": roic(f),
        "debt_to_equity": debt_to_equity(f),
    }
