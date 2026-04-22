"""
E2E pipeline tests — no live API calls.

Covers:
  - _passes_long / _passes_short filters
  - run_universe_screen / run_short_universe_screen (Track B / C)
  - _build_candidate: long DCF gate, short DCF gate, conviction gate, TV dropout
  - generate_signals: all four tracks, dedup, long/short counts
  - submit_bracket_order: whole-share floor, short side = "sell", plain-market fallback
  - _fetch_sync retry: 3 attempts on failure
  - loss_analyzer: parsed accessor via content[0].parsed
  - pipeline run.py: dry_run skips, correct Alpaca side per direction
"""
from __future__ import annotations

import math
from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# ── helpers ───────────────────────────────────────────────────────────────────

def _make_dcf(ticker: str = "AAPL", upside: float = 0.22, price: float = 100.0):
    from backend.valuation.engine import ValuationBundle
    from backend.valuation.models import Assumptions, DCFResult, SensitivityTable, WACCBreakdown
    dcf = DCFResult(
        ticker=ticker,
        as_of=date.today(),
        wacc=WACCBreakdown(
            cost_of_equity=Decimal("0.10"),
            cost_of_debt_after_tax=Decimal("0.03"),
            weight_equity=Decimal("0.90"),
            weight_debt=Decimal("0.10"),
            wacc=Decimal("0.09"),
        ),
        assumptions=Assumptions(),
        projections=[],
        pv_explicit=Decimal("500"),
        terminal_value=Decimal("1500"),
        pv_terminal=Decimal("1000"),
        enterprise_value=Decimal("1500"),
        net_debt=Decimal("0"),
        equity_value=Decimal("1500"),
        shares_outstanding=Decimal("10"),
        implied_share_price=Decimal(str(round(price * (1 + upside), 4))),
        current_price=Decimal(str(price)),
        upside_pct=Decimal(str(upside)),
    )
    return ValuationBundle(
        dcf=dcf,
        sensitivity=__import__("backend.valuation.models", fromlist=["SensitivityTable"]).SensitivityTable(
            wacc_axis=[], growth_axis=[], cells=[]
        ),
        monte_carlo=None,
        audit=[],
        auditor_ok=True,
    )


def _make_snap(rsi: float = 35.0, trend: str = "uptrend", tv: str = "BUY"):
    from backend.technicals.engine import TechnicalSnapshot
    return TechnicalSnapshot(
        ticker="X",
        as_of=date.today(),
        price=Decimal("100"),
        sma_50=Decimal("95"),
        sma_200=Decimal("90"),
        rsi_14=Decimal(str(rsi)),
        macd=Decimal("1.2"),
        macd_signal=Decimal("0.9"),
        macd_hist=Decimal("0.3"),
        w52_high=Decimal("120"),
        w52_low=Decimal("80"),
        distance_from_52w_high=Decimal("-0.17"),
        distance_from_52w_low=Decimal("0.25"),
        rel_strength_vs_spx=Decimal("1.05"),
        trend=trend,  # type: ignore[arg-type]
        tv_recommendation=tv,  # type: ignore[arg-type]
    )


def _make_conviction_row(
    ticker: str = "META",
    upside: float = 0.22,
    score: float = 8.0,
    source: str = "13f",
):
    from backend.filings.conviction_screener import ConvictionScreenRow
    return ConvictionScreenRow(
        rank=1,
        issuer=ticker,
        ticker=ticker,
        conviction_score=Decimal(str(score)),
        buyer_count=2,
        buyers=["Fund A", "Fund B"],
        max_weight_pct=Decimal("3.0"),
        is_consensus=False,
        upside_pct=Decimal(str(upside)),
        implied_price=Decimal(str(round(100 * (1 + upside), 2))),
        current_price=Decimal("100"),
        status="ok",
        source=source,
    )


def _make_signal(direction: str = "long") -> Any:
    from backend.nlp.equity_researcher import ReasonedTradeSignal
    return ReasonedTradeSignal(
        direction=direction,  # type: ignore[arg-type]
        strategy_type="swing",
        entry_rationale="test",
        entry_price_note="near support",
        stop_loss_note="below low",
        target_note="prior high",
        risk_reward_estimate=2.0,
        stop_loss_pct=3.0,
        target_pct=6.0,
        timeframe_alignment="aligned",
        key_risks=["macro"],
        confidence="medium",
        reasoning="test signal",
    )


# ── universe screener filters ─────────────────────────────────────────────────

class TestPassesFilters:
    def test_passes_long_all_conditions(self) -> None:
        from backend.filings.universe_screener import _passes_long
        snap = _make_snap(rsi=35, trend="uptrend", tv="BUY")
        assert _passes_long(snap) is True

    def test_passes_long_strong_buy(self) -> None:
        from backend.filings.universe_screener import _passes_long
        assert _passes_long(_make_snap(rsi=38, trend="uptrend", tv="STRONG_BUY")) is True

    def test_passes_long_rejects_high_rsi(self) -> None:
        from backend.filings.universe_screener import _passes_long
        assert _passes_long(_make_snap(rsi=41, trend="uptrend", tv="BUY")) is False

    def test_passes_long_rejects_downtrend(self) -> None:
        from backend.filings.universe_screener import _passes_long
        assert _passes_long(_make_snap(rsi=35, trend="downtrend", tv="BUY")) is False

    def test_passes_long_rejects_sell(self) -> None:
        from backend.filings.universe_screener import _passes_long
        assert _passes_long(_make_snap(rsi=35, trend="uptrend", tv="SELL")) is False

    def test_passes_long_rejects_none(self) -> None:
        from backend.filings.universe_screener import _passes_long
        assert _passes_long(None) is False

    def test_passes_short_all_conditions(self) -> None:
        from backend.filings.universe_screener import _passes_short
        snap = _make_snap(rsi=72, trend="downtrend", tv="STRONG_SELL")
        assert _passes_short(snap) is True

    def test_passes_short_sell(self) -> None:
        from backend.filings.universe_screener import _passes_short
        assert _passes_short(_make_snap(rsi=65, trend="downtrend", tv="SELL")) is True

    def test_passes_short_rejects_low_rsi(self) -> None:
        from backend.filings.universe_screener import _passes_short
        assert _passes_short(_make_snap(rsi=58, trend="downtrend", tv="STRONG_SELL")) is False

    def test_passes_short_rejects_uptrend(self) -> None:
        from backend.filings.universe_screener import _passes_short
        assert _passes_short(_make_snap(rsi=75, trend="uptrend", tv="STRONG_SELL")) is False

    def test_passes_short_rejects_buy(self) -> None:
        from backend.filings.universe_screener import _passes_short
        assert _passes_short(_make_snap(rsi=75, trend="downtrend", tv="BUY")) is False

    def test_passes_short_rejects_none(self) -> None:
        from backend.filings.universe_screener import _passes_short
        assert _passes_short(None) is False

    def test_boundary_rsi_exactly_40_fails_long(self) -> None:
        from backend.filings.universe_screener import _passes_long
        # RSI must be strictly < 40
        assert _passes_long(_make_snap(rsi=40.0, trend="uptrend", tv="BUY")) is False

    def test_boundary_rsi_exactly_60_fails_short(self) -> None:
        from backend.filings.universe_screener import _passes_short
        # RSI must be strictly > 60
        assert _passes_short(_make_snap(rsi=60.0, trend="downtrend", tv="SELL")) is False


# ── universe screener — long ──────────────────────────────────────────────────

class TestRunUniverseScreen:
    @pytest.mark.asyncio
    async def test_returns_passing_tickers(self) -> None:
        from backend.filings.universe_screener import run_universe_screen
        good_snap = _make_snap(rsi=35, trend="uptrend", tv="BUY")

        async def fake_compute(ticker: str):
            return good_snap

        with (
            patch("backend.filings.universe_screener._fetch_universe", new=AsyncMock(return_value=["AAPL", "MSFT"])),
            patch("backend.filings.universe_screener.compute_technicals", side_effect=fake_compute),
            patch("backend.filings.universe_screener._safe_valuate", new=AsyncMock(
                return_value=(Decimal("0.20"), Decimal("120"), Decimal("100"), "ok")
            )),
        ):
            rows = await run_universe_screen(min_upside_pct=Decimal("0.07"))

        assert len(rows) == 2
        assert all(r.source == "universe" for r in rows)
        assert all(r.upside_pct == Decimal("0.20") for r in rows)

    @pytest.mark.asyncio
    async def test_filters_tickers_below_upside_gate(self) -> None:
        from backend.filings.universe_screener import run_universe_screen
        good_snap = _make_snap(rsi=35, trend="uptrend", tv="BUY")

        with (
            patch("backend.filings.universe_screener._fetch_universe", new=AsyncMock(return_value=["AAPL"])),
            patch("backend.filings.universe_screener.compute_technicals", new=AsyncMock(return_value=good_snap)),
            patch("backend.filings.universe_screener._safe_valuate", new=AsyncMock(
                return_value=(Decimal("0.05"), Decimal("105"), Decimal("100"), "ok")  # below 7%
            )),
        ):
            rows = await run_universe_screen(min_upside_pct=Decimal("0.07"))

        assert rows == []

    @pytest.mark.asyncio
    async def test_skips_tech_failures(self) -> None:
        from backend.filings.universe_screener import run_universe_screen

        with (
            patch("backend.filings.universe_screener._fetch_universe", new=AsyncMock(return_value=["AAPL"])),
            patch("backend.filings.universe_screener.compute_technicals", new=AsyncMock(return_value=None)),
        ):
            rows = await run_universe_screen()

        assert rows == []


# ── universe screener — short ─────────────────────────────────────────────────

class TestRunShortUniverseScreen:
    @pytest.mark.asyncio
    async def test_returns_short_candidates(self) -> None:
        from backend.filings.universe_screener import run_short_universe_screen
        short_snap = _make_snap(rsi=72, trend="downtrend", tv="STRONG_SELL")

        with (
            patch("backend.filings.universe_screener._fetch_universe", new=AsyncMock(return_value=["NVDA"])),
            patch("backend.filings.universe_screener.compute_technicals", new=AsyncMock(return_value=short_snap)),
            patch("backend.filings.universe_screener._safe_valuate", new=AsyncMock(
                return_value=(Decimal("-0.30"), Decimal("70"), Decimal("100"), "ok")  # 30% overvalued
            )),
        ):
            rows = await run_short_universe_screen(max_downside_pct=Decimal("-0.15"))

        assert len(rows) == 1
        assert rows[0].source == "short_universe"
        assert rows[0].upside_pct == Decimal("-0.30")

    @pytest.mark.asyncio
    async def test_filters_insufficient_downside(self) -> None:
        from backend.filings.universe_screener import run_short_universe_screen
        short_snap = _make_snap(rsi=65, trend="downtrend", tv="SELL")

        with (
            patch("backend.filings.universe_screener._fetch_universe", new=AsyncMock(return_value=["NVDA"])),
            patch("backend.filings.universe_screener.compute_technicals", new=AsyncMock(return_value=short_snap)),
            patch("backend.filings.universe_screener._safe_valuate", new=AsyncMock(
                return_value=(Decimal("-0.08"), Decimal("92"), Decimal("100"), "ok")  # only 8% overvalued
            )),
        ):
            rows = await run_short_universe_screen(max_downside_pct=Decimal("-0.15"))

        assert rows == []

    @pytest.mark.asyncio
    async def test_sorts_by_highest_rsi_first(self) -> None:
        from backend.filings.universe_screener import run_short_universe_screen

        snaps = {
            "A": _make_snap(rsi=62, trend="downtrend", tv="SELL"),
            "B": _make_snap(rsi=80, trend="downtrend", tv="STRONG_SELL"),
        }

        async def fake_compute(ticker: str):
            return snaps.get(ticker)

        with (
            patch("backend.filings.universe_screener._fetch_universe", new=AsyncMock(return_value=["A", "B"])),
            patch("backend.filings.universe_screener.compute_technicals", side_effect=fake_compute),
            patch("backend.filings.universe_screener._safe_valuate", new=AsyncMock(
                return_value=(Decimal("-0.25"), Decimal("75"), Decimal("100"), "ok")
            )),
        ):
            rows = await run_short_universe_screen(max_downside_pct=Decimal("-0.15"))

        # B (RSI=80) should come before A (RSI=62)
        assert rows[0].ticker == "B"
        assert rows[1].ticker == "A"


# ── _build_candidate ──────────────────────────────────────────────────────────

class TestBuildCandidate:
    @pytest.mark.asyncio
    async def test_long_passes_dcf_gate_and_gets_signal(self) -> None:
        from backend.trading.signal_generator import _build_candidate
        row = _make_conviction_row(upside=0.22)

        with (
            patch("backend.trading.signal_generator.fetch_tv_multiframe", new=AsyncMock(return_value={"1D": {"rsi": 38}})),
            patch("backend.trading.signal_generator.reason_trade_signal", new=AsyncMock(return_value=_make_signal("long"))),
        ):
            c = await _build_candidate(row, "swing", "NASDAQ", "america", direction="long")

        assert c is not None
        assert c.side == "long"
        assert c.notional_usd == Decimal("1000")

    @pytest.mark.asyncio
    async def test_long_fails_dcf_gate(self) -> None:
        from backend.trading.signal_generator import _build_candidate
        row = _make_conviction_row(upside=0.05)  # below 10%

        c = await _build_candidate(row, "swing", "NASDAQ", "america", direction="long")

        assert c is not None
        assert c.side == "no_trade"
        assert c.skip_reason is not None
        assert "threshold" in c.skip_reason

    @pytest.mark.asyncio
    async def test_short_passes_dcf_gate(self) -> None:
        from backend.trading.signal_generator import _build_candidate
        row = _make_conviction_row(upside=-0.25, source="short_universe")

        with (
            patch("backend.trading.signal_generator.fetch_tv_multiframe", new=AsyncMock(return_value={"1D": {"rsi": 72}})),
            patch("backend.trading.signal_generator.reason_trade_signal", new=AsyncMock(return_value=_make_signal("short"))),
        ):
            c = await _build_candidate(
                row, "swing", "NASDAQ", "america",
                min_upside_pct=Decimal("-0.15"),
                direction="short",
            )

        assert c is not None
        assert c.side == "short"

    @pytest.mark.asyncio
    async def test_short_fails_dcf_gate_insufficient_overvaluation(self) -> None:
        from backend.trading.signal_generator import _build_candidate
        row = _make_conviction_row(upside=-0.08, source="short_universe")  # only 8% overvalued

        c = await _build_candidate(
            row, "swing", "NASDAQ", "america",
            min_upside_pct=Decimal("-0.15"),
            direction="short",
        )

        assert c is not None
        assert c.side == "no_trade"
        assert "insufficient" in (c.skip_reason or "")

    @pytest.mark.asyncio
    async def test_tv_failure_returns_no_trade(self) -> None:
        from backend.trading.signal_generator import _build_candidate
        row = _make_conviction_row(upside=0.22)

        with patch("backend.trading.signal_generator.fetch_tv_multiframe", new=AsyncMock(return_value={})):
            c = await _build_candidate(row, "swing", "NASDAQ", "america", direction="long")

        assert c is not None
        assert c.side == "no_trade"
        assert c.skip_reason == "no TradingView data available"

    @pytest.mark.asyncio
    async def test_conviction_score_below_threshold_skipped(self) -> None:
        from backend.trading.signal_generator import _build_candidate
        row = _make_conviction_row(upside=0.22, score=3.0)  # below _MIN_CONVICTION_SCORE=5

        c = await _build_candidate(row, "swing", "NASDAQ", "america", direction="long")

        assert c is not None
        assert c.side == "no_trade"
        assert "conviction score" in (c.skip_reason or "")

    @pytest.mark.asyncio
    async def test_none_ticker_returns_none(self) -> None:
        from backend.trading.signal_generator import _build_candidate
        from backend.filings.conviction_screener import ConvictionScreenRow
        row = ConvictionScreenRow(
            rank=1, issuer="UNKNOWN", ticker=None,
            conviction_score=Decimal("8"), buyer_count=1, buyers=["F"],
            max_weight_pct=Decimal("2"), is_consensus=False,
            upside_pct=Decimal("0.20"), implied_price=Decimal("120"),
            current_price=Decimal("100"), status="ticker_unresolved",
        )

        c = await _build_candidate(row, "swing", "NASDAQ", "america")
        assert c is None


# ── generate_signals (four-track) ─────────────────────────────────────────────

class TestGenerateSignals:
    def _mock_screen(self, rows):
        from backend.filings.conviction_screener import ConvictionScreenerResponse
        return ConvictionScreenerResponse(
            quarter="2025-12-31",
            dataset_label="Q4 2025",
            rows=rows,
            valuation_ok_count=len(rows),
            valuation_failed_count=0,
            fundamental_funds_scanned=10,
        )

    @pytest.mark.asyncio
    async def test_four_tracks_all_fire(self) -> None:
        from backend.trading.signal_generator import generate_signals

        long_row = _make_conviction_row("META", upside=0.22, source="13f")
        # Conviction screen also has a massively overvalued short candidate
        short_13f_row = _make_conviction_row("AMZN", upside=-0.55, source="13f")
        # Row with positive upside that appears in conviction screen but NOT in short universe
        universe_long = _make_conviction_row("AAPL", upside=0.15, source="universe")
        universe_short = _make_conviction_row("NVDA", upside=-0.20, source="short_universe")

        with (
            patch("backend.trading.signal_generator.run_conviction_screener", new=AsyncMock(
                return_value=self._mock_screen([long_row, short_13f_row])
            )),
            patch("backend.trading.signal_generator.run_universe_screen", new=AsyncMock(return_value=[universe_long])),
            patch("backend.trading.signal_generator.run_short_universe_screen", new=AsyncMock(return_value=[universe_short])),
            patch("backend.trading.signal_generator.fetch_tv_multiframe", new=AsyncMock(return_value={"1D": {"rsi": 40}})),
            patch("backend.trading.signal_generator.reason_trade_signal", new=AsyncMock(return_value=_make_signal("long"))),
        ):
            batch = await generate_signals()

        tickers = [c.ticker for c in batch.candidates]
        assert "META" in tickers    # Track A long
        assert "AMZN" in tickers    # Track D short (conviction screener, massively overvalued)
        assert "AAPL" in tickers    # Track B long (universe)
        assert "NVDA" in tickers    # Track C short (universe)

    @pytest.mark.asyncio
    async def test_deduplication_prevents_double_entry(self) -> None:
        from backend.trading.signal_generator import generate_signals

        # META appears in both 13F long track AND universe short track
        meta_long = _make_conviction_row("META", upside=0.22, source="13f")
        meta_short_universe = _make_conviction_row("META", upside=-0.20, source="short_universe")

        with (
            patch("backend.trading.signal_generator.run_conviction_screener", new=AsyncMock(
                return_value=self._mock_screen([meta_long])
            )),
            patch("backend.trading.signal_generator.run_universe_screen", new=AsyncMock(return_value=[])),
            patch("backend.trading.signal_generator.run_short_universe_screen", new=AsyncMock(return_value=[meta_short_universe])),
            patch("backend.trading.signal_generator.fetch_tv_multiframe", new=AsyncMock(return_value={"1D": {}})),
            patch("backend.trading.signal_generator.reason_trade_signal", new=AsyncMock(return_value=_make_signal("long"))),
        ):
            batch = await generate_signals()

        meta_candidates = [c for c in batch.candidates if c.ticker == "META"]
        assert len(meta_candidates) == 1, "META should appear exactly once after dedup"

    @pytest.mark.asyncio
    async def test_actionable_count_correct(self) -> None:
        from backend.trading.signal_generator import generate_signals

        rows = [
            _make_conviction_row("META", upside=0.22),
            _make_conviction_row("AMZN", upside=0.05),  # will fail DCF gate → no_trade
        ]

        with (
            patch("backend.trading.signal_generator.run_conviction_screener", new=AsyncMock(
                return_value=self._mock_screen(rows)
            )),
            patch("backend.trading.signal_generator.run_universe_screen", new=AsyncMock(return_value=[])),
            patch("backend.trading.signal_generator.run_short_universe_screen", new=AsyncMock(return_value=[])),
            patch("backend.trading.signal_generator.fetch_tv_multiframe", new=AsyncMock(return_value={"1D": {}})),
            patch("backend.trading.signal_generator.reason_trade_signal", new=AsyncMock(return_value=_make_signal("long"))),
        ):
            batch = await generate_signals()

        assert batch.actionable_count == 1
        assert batch.skipped_count == 1

    @pytest.mark.asyncio
    async def test_empty_tracks_produce_no_candidates(self) -> None:
        from backend.trading.signal_generator import generate_signals

        with (
            patch("backend.trading.signal_generator.run_conviction_screener", new=AsyncMock(
                return_value=self._mock_screen([])
            )),
            patch("backend.trading.signal_generator.run_universe_screen", new=AsyncMock(return_value=[])),
            patch("backend.trading.signal_generator.run_short_universe_screen", new=AsyncMock(return_value=[])),
        ):
            batch = await generate_signals()

        assert batch.candidates == []
        assert batch.actionable_count == 0


# ── alpaca bracket order ──────────────────────────────────────────────────────

class TestSubmitBracketOrder:
    @pytest.mark.asyncio
    async def test_whole_share_floor(self) -> None:
        """$1000 at $650/share should give qty=1 (not 1.53)."""
        from backend.trading.alpaca_trader import submit_bracket_order

        mock_order = MagicMock()
        mock_order.id = "order-123"
        mock_order.status = "accepted"
        mock_client = MagicMock()
        mock_client.submit_order.return_value = mock_order

        fake_ticker = MagicMock()
        fake_ticker.fast_info.last_price = 650.0

        with (
            patch("backend.trading.alpaca_trader._get_client", return_value=mock_client),
            patch("backend.trading.alpaca_trader.yf.Ticker", return_value=fake_ticker),
        ):
            result = await submit_bracket_order("META", "buy", Decimal("1000"), 3.0, 6.0)

        submitted_req = mock_client.submit_order.call_args[0][0]
        assert submitted_req.qty == 1
        assert submitted_req.qty == math.floor(1000 / 650)

    @pytest.mark.asyncio
    async def test_short_order_uses_sell_side(self) -> None:
        from backend.trading.alpaca_trader import submit_bracket_order
        from alpaca.trading.enums import OrderSide

        mock_order = MagicMock()
        mock_order.id = "short-order-456"
        mock_order.status = "accepted"
        mock_client = MagicMock()
        mock_client.submit_order.return_value = mock_order

        fake_ticker = MagicMock()
        fake_ticker.fast_info.last_price = 200.0

        with (
            patch("backend.trading.alpaca_trader._get_client", return_value=mock_client),
            patch("backend.trading.alpaca_trader.yf.Ticker", return_value=fake_ticker),
        ):
            result = await submit_bracket_order("AMZN", "sell", Decimal("1000"), 3.0, 6.0)

        submitted_req = mock_client.submit_order.call_args[0][0]
        assert submitted_req.side == OrderSide.SELL

    @pytest.mark.asyncio
    async def test_short_bracket_prices_flipped(self) -> None:
        """For shorts: stop is above entry, target is below entry."""
        from backend.trading.alpaca_trader import submit_bracket_order

        mock_order = MagicMock()
        mock_order.id = "x"
        mock_order.status = "accepted"
        mock_client = MagicMock()
        mock_client.submit_order.return_value = mock_order

        fake_ticker = MagicMock()
        fake_ticker.fast_info.last_price = 100.0

        with (
            patch("backend.trading.alpaca_trader._get_client", return_value=mock_client),
            patch("backend.trading.alpaca_trader.yf.Ticker", return_value=fake_ticker),
        ):
            result = await submit_bracket_order("TSLA", "sell", Decimal("1000"), 3.0, 6.0)

        assert result.stop_price == round(100.0 * 1.03, 2)   # stop above entry for short
        assert result.target_price == round(100.0 * 0.94, 2) # target below entry for short

    @pytest.mark.asyncio
    async def test_fallback_to_plain_market_on_alpaca_error(self) -> None:
        from backend.trading.alpaca_trader import submit_bracket_order

        mock_client = MagicMock()
        # First call (bracket) raises, second call (plain market) succeeds
        fallback_order = MagicMock()
        fallback_order.id = "fallback-789"
        fallback_order.status = "accepted"
        mock_client.submit_order.side_effect = [
            Exception('{"code":42210000,"message":"fractional orders must be simple orders"}'),
            fallback_order,
        ]

        fake_ticker = MagicMock()
        fake_ticker.fast_info.last_price = 500.0

        with (
            patch("backend.trading.alpaca_trader._get_client", return_value=mock_client),
            patch("backend.trading.alpaca_trader.yf.Ticker", return_value=fake_ticker),
        ):
            result = await submit_bracket_order("NVDA", "buy", Decimal("1000"), 3.0, 6.0)

        assert result.order_id == "fallback-789"
        assert result.status == "accepted"

    @pytest.mark.asyncio
    async def test_no_price_falls_back_to_plain_market(self) -> None:
        from backend.trading.alpaca_trader import submit_bracket_order

        mock_order = MagicMock()
        mock_order.id = "plain-order"
        mock_order.status = "accepted"
        mock_client = MagicMock()
        mock_client.submit_order.return_value = mock_order

        fake_ticker = MagicMock()
        fake_ticker.fast_info.last_price = None  # no price

        with (
            patch("backend.trading.alpaca_trader._get_client", return_value=mock_client),
            patch("backend.trading.alpaca_trader.yf.Ticker", return_value=fake_ticker),
        ):
            result = await submit_bracket_order("XYZ", "buy", Decimal("1000"), 3.0, 6.0)

        assert result.status == "accepted"


# ── TV retry ──────────────────────────────────────────────────────────────────

class TestTVRetry:
    def test_retries_3_times_on_failure(self) -> None:
        from backend.technicals.tv_enrichment import _fetch_sync

        call_count = 0

        def _flaky_handler(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("TV timeout")

        with patch("backend.technicals.tv_enrichment.TA_Handler", side_effect=_flaky_handler):
            result = _fetch_sync("AAPL", "america", "NASDAQ", "1D")

        assert result is None
        assert call_count == 3

    def test_returns_on_first_success(self) -> None:
        from backend.technicals.tv_enrichment import _fetch_sync

        call_count = 0

        def _handler(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            mock.summary = {"RECOMMENDATION": "BUY", "BUY": 10, "SELL": 2, "NEUTRAL": 3}
            mock.indicators = {"RSI": 38.0, "EMA20": 100.0, "EMA50": 95.0, "EMA200": 90.0,
                               "SMA50": 95.0, "SMA200": 90.0, "ADX": 25.0, "ATR": 2.0,
                               "volume": 1000000, "close": 150.0,
                               "MACD.macd": 1.2, "MACD.signal": 0.9,
                               "BB.upper": 160.0, "BB.lower": 140.0, "BBP": 0.7,
                               "RSI[1]": 37.0}
            return mock

        with patch("backend.technicals.tv_enrichment.TA_Handler", side_effect=_handler):
            result = _fetch_sync("AAPL", "america", "NASDAQ", "1D")

        assert result is not None
        assert call_count == 1

    def test_succeeds_on_second_attempt(self) -> None:
        from backend.technicals.tv_enrichment import _fetch_sync

        attempt = 0

        def _handler(*args, **kwargs):
            nonlocal attempt
            attempt += 1
            if attempt < 2:
                raise RuntimeError("transient")
            mock = MagicMock()
            mock.summary = {"RECOMMENDATION": "BUY", "BUY": 10, "SELL": 2, "NEUTRAL": 3}
            mock.indicators = {"RSI": 38.0, "EMA20": 100.0, "EMA50": 95.0, "EMA200": 90.0,
                               "SMA50": 95.0, "SMA200": 90.0, "ADX": 25.0, "ATR": 2.0,
                               "volume": 1000000, "close": 150.0,
                               "MACD.macd": 1.2, "MACD.signal": 0.9,
                               "BB.upper": 160.0, "BB.lower": 140.0, "BBP": 0.7,
                               "RSI[1]": 37.0}
            return mock

        with (
            patch("backend.technicals.tv_enrichment.TA_Handler", side_effect=_handler),
            patch("backend.technicals.tv_enrichment.time.sleep"),  # don't actually sleep
        ):
            result = _fetch_sync("AAPL", "america", "NASDAQ", "1D")

        assert result is not None
        assert attempt == 2


# ── pipeline run.py ───────────────────────────────────────────────────────────

class TestPipelineRun:
    def _make_batch(self, candidates):
        from backend.trading.signal_generator import SignalBatch
        actionable = sum(1 for c in candidates if c.side != "no_trade")
        return SignalBatch(
            strategy="swing",
            quarter="2025-12-31",
            candidates=candidates,
            actionable_count=actionable,
            skipped_count=len(candidates) - actionable,
        )

    def _make_order_result(self, ticker: str, side: str = "buy"):
        from backend.trading.alpaca_trader import OrderResult
        return OrderResult(
            ticker=ticker,
            side=side,  # type: ignore[arg-type]
            notional_usd=Decimal("1000"),
            order_id=f"order-{ticker}",
            status="accepted",
        )

    @pytest.mark.asyncio
    async def test_dry_run_skips_all_orders(self) -> None:
        from backend.pipeline.run import run

        long_c = _make_conviction_row("META", upside=0.22)
        short_c = _make_conviction_row("AMZN", upside=-0.30)

        # Patch to get TradeCandidate objects
        from backend.trading.signal_generator import TradeCandidate
        long_trade = TradeCandidate(
            ticker="META", side="long", notional_usd=Decimal("1000"),
            conviction_score=Decimal("8"), upside_pct=Decimal("0.22"),
            signal=_make_signal("long"),
        )
        short_trade = TradeCandidate(
            ticker="AMZN", side="short", notional_usd=Decimal("1000"),
            conviction_score=Decimal("7"), upside_pct=Decimal("-0.55"),
            signal=_make_signal("short"),
        )

        mock_submit = AsyncMock()

        with (
            patch("backend.pipeline.run.generate_signals", new=AsyncMock(
                return_value=self._make_batch([long_trade, short_trade])
            )),
            patch("backend.pipeline.run.submit_bracket_order", new=mock_submit),
            patch("backend.pipeline.run.get_supabase"),
        ):
            await run(strategy="swing", dry_run=True)

        mock_submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_long_uses_buy_side(self) -> None:
        from backend.pipeline.run import run
        from backend.trading.signal_generator import TradeCandidate

        long_trade = TradeCandidate(
            ticker="META", side="long", notional_usd=Decimal("1000"),
            conviction_score=Decimal("8"), upside_pct=Decimal("0.22"),
            signal=_make_signal("long"),
        )

        mock_submit = AsyncMock(return_value=self._make_order_result("META", "buy"))
        mock_sb = MagicMock()
        mock_sb.table.return_value.insert.return_value.execute.return_value = None

        with (
            patch("backend.pipeline.run.generate_signals", new=AsyncMock(
                return_value=self._make_batch([long_trade])
            )),
            patch("backend.pipeline.run.submit_bracket_order", new=mock_submit),
            patch("backend.pipeline.run.get_supabase", return_value=mock_sb),
        ):
            await run(strategy="swing", dry_run=False)

        mock_submit.assert_awaited_once()
        call_kwargs = mock_submit.call_args
        assert call_kwargs.kwargs["side"] == "buy"

    @pytest.mark.asyncio
    async def test_short_uses_sell_side(self) -> None:
        from backend.pipeline.run import run
        from backend.trading.signal_generator import TradeCandidate

        short_trade = TradeCandidate(
            ticker="AMZN", side="short", notional_usd=Decimal("1000"),
            conviction_score=Decimal("7"), upside_pct=Decimal("-0.55"),
            signal=_make_signal("short"),
        )

        mock_submit = AsyncMock(return_value=self._make_order_result("AMZN", "sell"))
        mock_sb = MagicMock()
        mock_sb.table.return_value.insert.return_value.execute.return_value = None

        with (
            patch("backend.pipeline.run.generate_signals", new=AsyncMock(
                return_value=self._make_batch([short_trade])
            )),
            patch("backend.pipeline.run.submit_bracket_order", new=mock_submit),
            patch("backend.pipeline.run.get_supabase", return_value=mock_sb),
        ):
            await run(strategy="swing", dry_run=False)

        mock_submit.assert_awaited_once()
        call_kwargs = mock_submit.call_args
        assert call_kwargs.kwargs["side"] == "sell"

    @pytest.mark.asyncio
    async def test_no_trade_candidates_skipped(self) -> None:
        from backend.pipeline.run import run
        from backend.trading.signal_generator import TradeCandidate
        from backend.trading.signal_generator import _null_signal

        no_trade = TradeCandidate(
            ticker="GOOGL", side="no_trade", notional_usd=Decimal("0"),
            conviction_score=Decimal("6"), upside_pct=Decimal("-0.38"),
            signal=_null_signal("GOOGL", "swing"),
        )

        mock_submit = AsyncMock()

        with (
            patch("backend.pipeline.run.generate_signals", new=AsyncMock(
                return_value=self._make_batch([no_trade])
            )),
            patch("backend.pipeline.run.submit_bracket_order", new=mock_submit),
            patch("backend.pipeline.run.get_supabase"),
        ):
            await run(strategy="swing", dry_run=False)

        mock_submit.assert_not_called()


# ── loss_analyzer parsed accessor ─────────────────────────────────────────────

class TestLossAnalyzerParsedAccessor:
    @pytest.mark.asyncio
    async def test_parsed_via_content_block(self) -> None:
        from backend.trading.loss_analyzer import LossAnalysis, analyze_losses

        fake_analysis = LossAnalysis(
            analyzed_at="2026-04-22T00:00:00+00:00",
            total_positions_reviewed=0,
            losing_positions=0,
            avg_unrealized_pnl_pct=0.0,
            patterns=[],
            threshold_adjustments=[],
            overall_assessment="No trades yet — system healthy.",
            market_regime_note="Market neutral.",
        )

        # Simulate response.content[0].parsed
        mock_content_block = MagicMock()
        mock_content_block.parsed = fake_analysis
        mock_response = MagicMock()
        mock_response.content = [mock_content_block]

        mock_anthropic = MagicMock()
        mock_anthropic.messages.parse = AsyncMock(return_value=mock_response)

        with (
            patch("backend.trading.loss_analyzer._get_anthropic", return_value=mock_anthropic),
            patch("backend.trading.loss_analyzer.get_open_positions", new=AsyncMock(return_value=[])),
            patch("backend.trading.loss_analyzer._get_account_activities", return_value=[]),
            patch("backend.trading.loss_analyzer._get_recent_trades_from_supabase", return_value=[]),
        ):
            result = await analyze_losses(lookback_days=14)

        assert result.overall_assessment == "No trades yet — system healthy."
        assert result.losing_positions == 0

    @pytest.mark.asyncio
    async def test_no_thinking_param_sent(self) -> None:
        """Ensure thinking is NOT passed — it breaks output_format structured output."""
        from backend.trading.loss_analyzer import analyze_losses

        mock_content_block = MagicMock()
        mock_content_block.parsed = MagicMock(
            total_positions_reviewed=0,
            losing_positions=0,
            avg_unrealized_pnl_pct=0.0,
            patterns=[],
            threshold_adjustments=[],
            overall_assessment="ok",
            market_regime_note="neutral",
        )
        mock_response = MagicMock()
        mock_response.content = [mock_content_block]

        mock_parse = AsyncMock(return_value=mock_response)
        mock_anthropic = MagicMock()
        mock_anthropic.messages.parse = mock_parse

        with (
            patch("backend.trading.loss_analyzer._get_anthropic", return_value=mock_anthropic),
            patch("backend.trading.loss_analyzer.get_open_positions", new=AsyncMock(return_value=[])),
            patch("backend.trading.loss_analyzer._get_account_activities", return_value=[]),
            patch("backend.trading.loss_analyzer._get_recent_trades_from_supabase", return_value=[]),
        ):
            await analyze_losses()

        call_kwargs = mock_parse.call_args.kwargs
        assert "thinking" not in call_kwargs, "thinking param must not be passed to messages.parse with output_format"
