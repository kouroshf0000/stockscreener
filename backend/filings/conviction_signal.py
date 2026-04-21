from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from backend.filings.thirteenf import fetch_hedge_fund_digests

# Quant funds: their new positions are hedge legs, not investment theses
QUANT_SLUGS: frozenset[str] = frozenset({
    "citadel-advisors",
    "d-e-shaw",
    "two-sigma-investments",
    "renaissance-technologies",
    "millennium-management",
})

# Weight each fund's signal by how concentrated and fundamental they are
FUND_QUALITY: dict[str, float] = {
    "pershing-square-capital-management": 1.5,
    "elliott-investment-management": 1.4,
    "trian-fund-management": 1.4,
    "jana-partners": 1.3,
    "tiger-global-management": 1.3,
    "viking-global-investors": 1.2,
    "soroban-capital-partners": 1.2,
    "coatue-management": 1.1,
    "lone-pine-capital": 1.1,
    "third-point": 1.1,
    "the-baupost-group": 1.1,
    "duquesne-family-office": 1.1,
    "bridgewater-associates": 0.8,  # macro/ETF-heavy
}


class ConvictionBuy(BaseModel):
    model_config = ConfigDict(frozen=True)

    issuer: str
    cusip: str
    buyer_count: int
    buyers: list[str]
    total_weight_pct: Decimal
    max_weight_pct: Decimal
    conviction_score: Decimal
    is_consensus: bool  # True if 3+ funds bought it


class ConvictionSignalResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    quarter: str
    dataset_label: str
    signals: list[ConvictionBuy]
    min_weight_pct: Decimal
    fundamental_funds_scanned: int


async def run_conviction_signal(
    min_weight_pct: float = 1.0,
    min_buyers: int = 1,
    top_n: int = 30,
) -> ConvictionSignalResponse:
    """
    Scan 13F new positions across all fundamental (non-quant) funds.
    Score each new buy by: position size, fund quality weight, buyer convergence.
    Returns top_n ranked signals.
    """
    digest = await fetch_hedge_fund_digests(limit=25, top_positions=10)

    buy_map: dict[str, dict] = defaultdict(lambda: {
        "cusip": "",
        "buyers": [],
        "weights": [],
        "raw_score": 0.0,
    })

    fundamental_funds = [m for m in digest.managers if m.manager_slug not in QUANT_SLUGS]

    for m in fundamental_funds:
        quality = FUND_QUALITY.get(m.manager_slug, 1.0)
        for p in m.new_positions:
            w = float(p.weight_pct)
            if w < min_weight_pct:
                continue
            key = p.issuer.strip().upper()
            entry = buy_map[key]
            entry["cusip"] = entry["cusip"] or p.cusip
            entry["buyers"].append(m.manager_name)
            entry["weights"].append(w)
            # Score: weight * fund quality, boosted quadratically for consensus
            entry["raw_score"] += w * quality

    signals: list[ConvictionBuy] = []
    for issuer, data in buy_map.items():
        buyers = data["buyers"]
        if len(buyers) < min_buyers:
            continue
        weights = data["weights"]
        n = len(buyers)
        # Consensus multiplier: 2+ funds = 1.5x, 3+ = 2x
        consensus_mult = 2.0 if n >= 3 else (1.5 if n >= 2 else 1.0)
        score = data["raw_score"] * consensus_mult

        signals.append(ConvictionBuy(
            issuer=issuer,
            cusip=data["cusip"],
            buyer_count=n,
            buyers=buyers,
            total_weight_pct=Decimal(str(round(sum(weights), 2))),
            max_weight_pct=Decimal(str(round(max(weights), 2))),
            conviction_score=Decimal(str(round(score, 3))),
            is_consensus=n >= 3,
        ))

    signals.sort(key=lambda x: float(x.conviction_score), reverse=True)

    quarter = str(digest.managers[0].period_of_report) if digest.managers else "unknown"

    return ConvictionSignalResponse(
        quarter=quarter,
        dataset_label=digest.latest_dataset_label,
        signals=signals[:top_n],
        min_weight_pct=Decimal(str(min_weight_pct)),
        fundamental_funds_scanned=len(fundamental_funds),
    )
