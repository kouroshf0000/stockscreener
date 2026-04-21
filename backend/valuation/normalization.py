from __future__ import annotations

from decimal import Decimal

from backend.data_providers.models import FinancialStatement, Fundamentals

_NONRECURRING_KEYWORDS = (
    "litigation",
    "settlement",
    "impairment",
    "restructuring",
    "goodwill",
    "one-time",
    "divestiture",
    "gain on sale",
)


def _is_nonrecurring(label: str) -> bool:
    l = label.lower()
    return any(k in l for k in _NONRECURRING_KEYWORDS)


def normalized_fcf_series(f: Fundamentals) -> list[Decimal]:
    out: list[Decimal] = []
    for s in f.statements:
        if s.free_cash_flow is None:
            continue
        adj = s.free_cash_flow
        payload = getattr(s, "__pydantic_extra__", None) or {}
        for k, v in payload.items():
            if _is_nonrecurring(k) and isinstance(v, Decimal):
                adj -= v
        out.append(adj)
    return out


def base_revenue(f: Fundamentals) -> Decimal | None:
    for s in f.statements:
        if s.revenue is not None and s.revenue > 0:
            return s.revenue
    return None


def latest(f: Fundamentals) -> FinancialStatement | None:
    return f.statements[0] if f.statements else None
