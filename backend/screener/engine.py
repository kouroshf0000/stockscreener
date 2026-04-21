from __future__ import annotations

import asyncio
import statistics
from collections import defaultdict
from decimal import Decimal

from backend.data_providers.yfinance_client import fetch_fundamentals
from backend.screener.dsl import (
    Filter,
    ScreenRequest,
    ScreenResponse,
    ScreenRow,
    evaluate,
)
from backend.screener.etf_holdings import overlap_with
from backend.screener.metrics import compute_all
from backend.screener.universe import universe_for


async def _row_for(symbol: str) -> ScreenRow | None:
    try:
        f = await fetch_fundamentals(symbol)
    except Exception:
        return None
    metrics = compute_all(f)
    return ScreenRow(
        symbol=f.ticker,
        sector=f.sector,
        price=f.price,
        market_cap=f.market_cap,
        metrics=metrics,
    )


def _sector_medians(rows: list[ScreenRow]) -> dict[str, dict[str, Decimal]]:
    buckets: dict[str, dict[str, list[Decimal]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if not r.sector:
            continue
        for k, v in r.metrics.items():
            if v is not None:
                buckets[r.sector][k].append(v)
    out: dict[str, dict[str, Decimal]] = {}
    for sec, metric_map in buckets.items():
        out[sec] = {}
        for k, vals in metric_map.items():
            if vals:
                med = statistics.median(float(x) for x in vals)
                out[sec][k] = Decimal(str(round(med, 8)))
    return out


_SEM = asyncio.Semaphore(8)  # throttle concurrent yfinance calls


async def _row_for_throttled(symbol: str) -> ScreenRow | None:
    async with _SEM:
        return await _row_for(symbol)


async def run_screen(req: ScreenRequest) -> ScreenResponse:
    symbols = universe_for(req.universe)
    if not symbols:
        return ScreenResponse(total=0, rows=[], etf_overlap=[])

    results = await asyncio.gather(*(_row_for_throttled(s) for s in symbols))
    rows: list[ScreenRow] = [r for r in results if r is not None]
    medians = _sector_medians(rows)

    filtered = [r for r in rows if evaluate(r, req.filters, medians)]
    filtered.sort(key=lambda r: r.market_cap or Decimal(0), reverse=True)
    filtered = filtered[: req.limit]

    overlap: list[str] = []
    if req.etf_overlap:
        overlap = overlap_with([r.symbol for r in filtered], req.etf_overlap)

    return ScreenResponse(total=len(filtered), rows=filtered, etf_overlap=overlap)


__all__ = ["Filter", "ScreenRequest", "ScreenResponse", "ScreenRow", "run_screen"]
