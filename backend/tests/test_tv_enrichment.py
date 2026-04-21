from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.technicals.tv_enrichment import fetch_tv_analysis


@pytest.mark.asyncio
async def test_fetch_tv_analysis_success() -> None:
    mock_result = {
        "recommendation": "BUY",
        "bb_upper": 210.5,
        "bb_lower": 195.0,
        "bb_pct_b": 0.72,
        "adx": 28.3,
        "atr": 3.1,
        "patterns": ["Candle.Hammer"],
    }
    with patch("backend.technicals.tv_enrichment._fetch_sync", return_value=mock_result):
        result = await fetch_tv_analysis("AAPL")
    assert result is not None
    assert result["recommendation"] == "BUY"
    assert result["adx"] == 28.3
    assert "Candle.Hammer" in result["patterns"]


@pytest.mark.asyncio
async def test_fetch_tv_analysis_graceful_failure() -> None:
    with patch("backend.technicals.tv_enrichment._fetch_sync", return_value=None):
        result = await fetch_tv_analysis("INVALID_TICKER")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_tv_analysis_exception_returns_none() -> None:
    def _raise(*_a: object, **_kw: object) -> None:
        raise RuntimeError("TV down")

    with patch("backend.technicals.tv_enrichment._fetch_sync", side_effect=_raise):
        result = await fetch_tv_analysis("AAPL")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_tv_analysis_no_patterns_when_all_zero() -> None:
    mock_result = {
        "recommendation": "NEUTRAL",
        "bb_upper": 205.0,
        "bb_lower": 190.0,
        "bb_pct_b": 0.5,
        "adx": 18.0,
        "atr": 2.5,
        "patterns": [],
    }
    with patch("backend.technicals.tv_enrichment._fetch_sync", return_value=mock_result):
        result = await fetch_tv_analysis("MSFT")
    assert result is not None
    assert result["patterns"] == []
