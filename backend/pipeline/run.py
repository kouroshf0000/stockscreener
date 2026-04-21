"""
Market-open pipeline — runs at 9:30 AM ET Mon-Fri via GitHub Actions.
Conviction screener → Claude trade signals → Alpaca paper orders → Supabase ledger.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone

from backend.app.supabase_client import get_supabase
from backend.trading.signal_generator import generate_signals
from backend.trading.alpaca_trader import submit_bracket_order, get_open_positions, close_position

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("pipeline")


async def run(
    strategy: str = "swing",
    top_n: int = 10,
    dry_run: bool = False,
) -> None:
    started = datetime.now(timezone.utc)
    logger.info("pipeline start | strategy=%s top_n=%d dry_run=%s", strategy, top_n, dry_run)

    batch = await generate_signals(strategy=strategy, top_n=top_n)  # type: ignore[arg-type]

    logger.info(
        "signals ready | actionable=%d skipped=%d quarter=%s",
        batch.actionable_count, batch.skipped_count, batch.quarter,
    )

    orders = []
    for candidate in batch.candidates:
        if candidate.side == "no_trade" or candidate.ticker is None:
            logger.info("skip %s — %s", candidate.ticker, candidate.skip_reason or candidate.signal.direction)
            continue

        logger.info(
            "signal %s | %s | conf=%s | RR=%.1f | upside=%.1f%%",
            candidate.ticker, candidate.side,
            candidate.signal.confidence,
            candidate.signal.risk_reward_estimate,
            float(candidate.upside_pct or 0) * 100,
        )

        if dry_run:
            logger.info("dry_run — skipping order for %s", candidate.ticker)
            continue

        side = "buy" if candidate.side == "long" else "sell"
        result = await submit_bracket_order(
            ticker=candidate.ticker,
            side=side,
            notional_usd=candidate.notional_usd,
            stop_loss_pct=candidate.signal.stop_loss_pct if candidate.signal.stop_loss_pct > 0 else 3.0,
            target_pct=candidate.signal.target_pct if candidate.signal.target_pct > 0 else 6.0,
        )
        orders.append(result)
        logger.info("order %s | %s | status=%s", result.ticker, result.order_id, result.status)

        # Persist to Supabase
        try:
            get_supabase().table("paper_trades").insert({
                "ticker": result.ticker,
                "side": result.side,
                "notional_usd": float(result.notional_usd),
                "order_id": result.order_id,
                "status": result.status,
                "strategy": strategy,
                "conviction_score": float(candidate.conviction_score),
                "upside_pct": float(candidate.upside_pct) if candidate.upside_pct else None,
                "signal_direction": candidate.signal.direction,
                "signal_confidence": candidate.signal.confidence,
                "entry_rationale": candidate.signal.entry_rationale,
                "stop_loss_pct": float(candidate.signal.stop_loss_pct) if hasattr(candidate.signal, 'stop_loss_pct') else None,
                "target_pct": float(candidate.signal.target_pct) if hasattr(candidate.signal, 'target_pct') else None,
                "stop_price": result.stop_price,
                "target_price": result.target_price,
            }).execute()
        except Exception as e:
            logger.warning("supabase write failed: %s", e)

    # Persist screener run summary
    try:
        get_supabase().table("conviction_screen_runs").insert({
            "quarter": batch.quarter,
            "dataset_label": f"pipeline {started.date()}",
            "rows": json.loads(batch.model_dump_json())["candidates"],
            "valuation_ok_count": batch.actionable_count,
            "valuation_failed_count": batch.skipped_count,
        }).execute()
    except Exception as e:
        logger.warning("screener run persist failed: %s", e)

    # Self-healing: analyze losses and log insights
    if not dry_run:
        try:
            from backend.trading.loss_analyzer import analyze_losses
            analysis = await analyze_losses(lookback_days=14)
            logger.info(
                "loss_analysis | losing_positions=%d | assessment=%s",
                analysis.losing_positions,
                analysis.overall_assessment[:120],
            )
            if analysis.threshold_adjustments:
                for adj in analysis.threshold_adjustments:
                    logger.info(
                        "suggested_adjustment | %s: %s → %s | %s",
                        adj.parameter, adj.current_value, adj.suggested_value, adj.rationale[:80],
                    )
        except Exception as e:
            logger.warning("loss analysis failed (non-blocking): %s", e)

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    logger.info(
        "pipeline done | orders=%d elapsed=%.1fs",
        len(orders), elapsed,
    )


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", default="swing", choices=["swing", "day"])
    p.add_argument("--top-n", type=int, default=10)
    p.add_argument("--dry-run", action="store_true", default=False)
    args = p.parse_args()
    asyncio.run(run(strategy=args.strategy, top_n=args.top_n, dry_run=args.dry_run))
