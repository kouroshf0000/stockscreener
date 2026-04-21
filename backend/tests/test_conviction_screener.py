from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from backend.filings.conviction_screener import (
    ConvictionScreenerResponse,
    _resolve_ticker,
    run_conviction_screener,
)
from backend.filings.conviction_signal import (
    ConvictionBuy,
    ConvictionSignalResponse,
)


def _make_signal(n: int = 3) -> ConvictionSignalResponse:
    signals = []
    issuers = [
        ("AMAZON COM INC", "023135106"),
        ("FISERV INC", "337738108"),
        ("UNKNOWN CORP XYZ", "999999999"),
    ]
    for i, (issuer, cusip) in enumerate(issuers[:n]):
        signals.append(
            ConvictionBuy(
                issuer=issuer,
                cusip=cusip,
                buyer_count=2 - (i % 2),
                buyers=["Fund A", "Fund B"][: 2 - (i % 2)],
                total_weight_pct=Decimal(str(5.0 - i)),
                max_weight_pct=Decimal(str(3.0 - i * 0.5)),
                conviction_score=Decimal(str(10.0 - i * 2)),
                is_consensus=False,
            )
        )
    return ConvictionSignalResponse(
        quarter="2025-12-31",
        dataset_label="Q4 2025",
        signals=signals,
        min_weight_pct=Decimal("1.0"),
        fundamental_funds_scanned=10,
    )


def test_resolve_ticker_known() -> None:
    assert _resolve_ticker("AMAZON COM INC") == "AMZN"
    assert _resolve_ticker("  meta platforms inc  ".upper()) == "META"


def test_resolve_ticker_unknown() -> None:
    assert _resolve_ticker("MADE UP COMPANY LLC") is None


@pytest.mark.asyncio
async def test_run_conviction_screener_structure() -> None:
    mock_signal = _make_signal(3)

    async def mock_valuate(ticker: str, **_):
        from backend.valuation.engine import ValuationBundle
        from backend.valuation.models import DCFResult, WACCBreakdown, Assumptions, SensitivityTable
        from datetime import date

        dcf = DCFResult(
            ticker=ticker,
            as_of=date.today(),
            wacc=WACCBreakdown(
                cost_of_equity=Decimal("0.10"),
                cost_of_debt_after_tax=Decimal("0.04"),
                weight_equity=Decimal("0.80"),
                weight_debt=Decimal("0.20"),
                wacc=Decimal("0.09"),
            ),
            assumptions=Assumptions(),
            projections=[],
            pv_explicit=Decimal("100"),
            terminal_value=Decimal("900"),
            pv_terminal=Decimal("600"),
            enterprise_value=Decimal("700"),
            net_debt=Decimal("50"),
            equity_value=Decimal("650"),
            shares_outstanding=Decimal("10"),
            implied_share_price=Decimal("65"),
            current_price=Decimal("50"),
            upside_pct=Decimal("30.0"),
        )
        return ValuationBundle(
            dcf=dcf,
            sensitivity=SensitivityTable(wacc_axis=[], growth_axis=[], cells=[]),
            monte_carlo=None,
            audit=[],
            auditor_ok=True,
        )

    with (
        patch("backend.filings.conviction_screener.run_conviction_signal", new=AsyncMock(return_value=mock_signal)),
        patch("backend.filings.conviction_screener.valuate", new=mock_valuate),
    ):
        result = await run_conviction_screener(top_n=3)

    assert isinstance(result, ConvictionScreenerResponse)
    assert len(result.rows) == 3

    # First two have known tickers → should be ok
    assert result.rows[0].ticker == "AMZN"
    assert result.rows[0].status == "ok"
    assert result.rows[1].ticker == "FISV"
    assert result.rows[1].status == "ok"

    # Third has unknown issuer → ticker_unresolved
    assert result.rows[2].ticker is None
    assert result.rows[2].status == "ticker_unresolved"

    # Ranks are 1-indexed and ascending
    assert [r.rank for r in result.rows] == [1, 2, 3]

    assert result.valuation_ok_count == 2
    assert result.valuation_failed_count == 1


@pytest.mark.asyncio
async def test_run_conviction_screener_top_n_respected() -> None:
    mock_signal = _make_signal(3)
    mock_signal_top1 = mock_signal.model_copy(update={"signals": mock_signal.signals[:1]})

    with patch("backend.filings.conviction_screener.run_conviction_signal", new=AsyncMock(return_value=mock_signal_top1)):
        with patch("backend.filings.conviction_screener.valuate", new=AsyncMock(side_effect=Exception("no network"))):
            result = await run_conviction_screener(top_n=1)

    assert len(result.rows) == 1
