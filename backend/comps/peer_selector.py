from __future__ import annotations

import asyncio
from decimal import Decimal

from backend.comps.peer_map import PEER_OVERRIDES
from backend.data_providers.models import Fundamentals
from backend.data_providers.yfinance_client import fetch_fundamentals
from backend.screener.universe import universe_for

SIZE_BAND_LOW = Decimal("0.25")
SIZE_BAND_HIGH = Decimal("4")
MIN_MARKET_CAP_FOR_LIQUIDITY = Decimal("1_000_000_000")


async def select_peers(
    ticker: str,
    universe_name: str = "SP500",
    max_peers: int = 8,
) -> list[str]:
    """
    Bulge-bracket peer selection:
      1. Prefer curated overrides (analyst-validated direct competitors).
      2. Else: filter universe by same sector + same industry + market cap band [0.25x, 4x target] + liquidity.
      3. Rank by market-cap proximity to target.
    """
    sym = ticker.upper()
    if sym in PEER_OVERRIDES:
        return PEER_OVERRIDES[sym][:max_peers]

    try:
        target = await fetch_fundamentals(sym)
    except Exception:
        return []
    if target.market_cap is None or target.sector is None:
        return []

    universe = [s for s in universe_for(universe_name) if s != sym]

    async def _peer_row(s: str) -> Fundamentals | None:
        try:
            return await fetch_fundamentals(s)
        except Exception:
            return None

    rows = await asyncio.gather(*(_peer_row(s) for s in universe))
    candidates: list[tuple[str, Decimal]] = []
    lo = target.market_cap * SIZE_BAND_LOW
    hi = target.market_cap * SIZE_BAND_HIGH
    for f in rows:
        if f is None or f.market_cap is None:
            continue
        if f.market_cap < MIN_MARKET_CAP_FOR_LIQUIDITY:
            continue
        if f.sector != target.sector:
            continue
        if target.industry and f.industry and f.industry != target.industry:
            continue
        if not (lo <= f.market_cap <= hi):
            continue
        distance = abs(f.market_cap - target.market_cap)
        candidates.append((f.ticker, distance))

    candidates.sort(key=lambda x: x[1])
    return [t for t, _ in candidates[:max_peers]]
