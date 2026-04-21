from __future__ import annotations

from typing import Any

from backend.app.logging import logger
from backend.hunter.engine import run_hunt


async def nightly_hunt(_ctx: dict[str, Any], universe: str = "SP500", top_n: int = 5) -> str:
    logger.info("hunt.start", universe=universe, top_n=top_n)
    report = await run_hunt(universe_name=universe, top_n=top_n)
    logger.info(
        "hunt.finish",
        run_id=report.run_id,
        candidates=report.candidates_evaluated,
        picks=len(report.picks),
        rejected=len(report.rejected),
    )
    return report.run_id


async def valuate_one(_ctx: dict[str, Any], ticker: str) -> dict[str, Any]:
    from backend.valuation.engine import valuate

    bundle = await valuate(ticker)
    return {
        "ticker": bundle.dcf.ticker,
        "implied_price": str(bundle.dcf.implied_share_price),
        "upside": str(bundle.dcf.upside_pct) if bundle.dcf.upside_pct else None,
    }
