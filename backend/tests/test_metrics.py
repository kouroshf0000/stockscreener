from __future__ import annotations

from datetime import date
from decimal import Decimal

from backend.data_providers.models import FinancialStatement, Fundamentals
from backend.screener.metrics import (
    compute_all,
    debt_to_equity,
    ev_ebitda,
    fcf_yield,
    pe_ratio,
    revenue_cagr_3y,
    roic,
)


def _f(statements: list[FinancialStatement], market_cap: Decimal | None = None) -> Fundamentals:
    return Fundamentals(
        ticker="TEST",
        sector="Technology",
        market_cap=market_cap,
        statements=statements,
        as_of=date(2026, 4, 17),
    )


def _stmt(period: str, **kwargs: Decimal | None) -> FinancialStatement:
    return FinancialStatement(period_end=date.fromisoformat(period), **kwargs)


def test_pe_ratio_basic() -> None:
    f = _f([_stmt("2025-12-31", net_income=Decimal("100"))], market_cap=Decimal("2000"))
    assert pe_ratio(f) == Decimal("20")


def test_pe_ratio_none_when_negative_earnings() -> None:
    f = _f([_stmt("2025-12-31", net_income=Decimal("-5"))], market_cap=Decimal("2000"))
    assert pe_ratio(f) is None


def test_ev_ebitda() -> None:
    f = _f(
        [
            _stmt(
                "2025-12-31",
                ebitda=Decimal("100"),
                total_debt=Decimal("200"),
                cash_and_equivalents=Decimal("50"),
            )
        ],
        market_cap=Decimal("1000"),
    )
    assert ev_ebitda(f) == Decimal("1150") / Decimal("100")


def test_fcf_yield() -> None:
    f = _f([_stmt("2025-12-31", free_cash_flow=Decimal("50"))], market_cap=Decimal("1000"))
    assert fcf_yield(f) == Decimal("0.05")


def test_revenue_cagr_3y() -> None:
    stmts = [
        _stmt("2025-12-31", revenue=Decimal("2000")),
        _stmt("2024-12-31", revenue=Decimal("1600")),
        _stmt("2023-12-31", revenue=Decimal("1200")),
        _stmt("2022-12-31", revenue=Decimal("1000")),
    ]
    cagr = revenue_cagr_3y(_f(stmts))
    assert cagr is not None
    assert abs(float(cagr) - (2 ** (1 / 3) - 1)) < 1e-4


def test_roic_and_dte() -> None:
    f = _f(
        [
            _stmt(
                "2025-12-31",
                operating_income=Decimal("120"),
                total_equity=Decimal("500"),
                total_debt=Decimal("300"),
                tax_rate=Decimal("0.25"),
            )
        ]
    )
    nopat = Decimal("120") * Decimal("0.75")
    assert roic(f) == nopat / Decimal("800")
    assert debt_to_equity(f) == Decimal("300") / Decimal("500")


def test_compute_all_keys() -> None:
    f = _f([_stmt("2025-12-31", net_income=Decimal("100"))], market_cap=Decimal("1000"))
    out = compute_all(f)
    assert set(out.keys()) == {
        "pe_ratio",
        "ev_ebitda",
        "fcf_yield",
        "revenue_cagr_3y",
        "roic",
        "debt_to_equity",
    }
