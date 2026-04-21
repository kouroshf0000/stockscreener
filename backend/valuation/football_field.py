from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from backend.comps.engine import CompsResult
from backend.technicals.engine import TechnicalSnapshot
from backend.valuation.scenarios import ScenarioBundle


class FootballFieldRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    label: str
    low: Decimal
    high: Decimal
    midpoint: Decimal


class FootballField(BaseModel):
    model_config = ConfigDict(frozen=True)
    current_price: Decimal | None
    rows: list[FootballFieldRow]


def _row(label: str, values: list[Decimal]) -> FootballFieldRow | None:
    clean = [v for v in values if v is not None and v > 0]
    if not clean:
        return None
    lo = min(clean)
    hi = max(clean)
    mid = (lo + hi) / Decimal(2)
    return FootballFieldRow(label=label, low=lo, high=hi, midpoint=mid)


def build_football_field(
    current_price: Decimal | None,
    scenarios: ScenarioBundle | None,
    comps: CompsResult | None,
    technicals: TechnicalSnapshot | None,
) -> FootballField:
    rows: list[FootballFieldRow] = []

    if scenarios is not None:
        dcf_row = _row(
            "DCF (bear/base/bull)",
            [scenarios.bear.implied_price, scenarios.base.implied_price, scenarios.bull.implied_price],
        )
        if dcf_row:
            rows.append(dcf_row)

    if comps is not None:
        comps_prices: list[Decimal] = []
        for m in comps.multiples:
            if m.implied_price is not None and m.implied_price > 0:
                comps_prices.append(m.implied_price)
        comps_row = _row("Trading comps (implied range)", comps_prices)
        if comps_row:
            rows.append(comps_row)

    if technicals is not None:
        range_row = _row(
            "52-week range",
            [technicals.w52_low, technicals.w52_high] if technicals.w52_low and technicals.w52_high else [],
        )
        if range_row:
            rows.append(range_row)

    return FootballField(current_price=current_price, rows=rows)
