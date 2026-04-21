from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

Op = Literal["gt", "gte", "lt", "lte", "eq"]
Metric = str


class Filter(BaseModel):
    model_config = ConfigDict(frozen=True)
    metric: Metric
    op: Op
    value: Decimal
    vs_sector: bool = False


class ScreenRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    universe: str = "SP500"
    filters: list[Filter] = []
    etf_overlap: str | None = None
    limit: int = 50


class ScreenRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    symbol: str
    sector: str | None
    price: Decimal | None
    market_cap: Decimal | None
    metrics: dict[str, Decimal | None]


class ScreenResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    total: int
    rows: list[ScreenRow]
    etf_overlap: list[str] = []


def _cmp(a: Decimal, op: Op, b: Decimal) -> bool:
    if op == "gt":
        return a > b
    if op == "gte":
        return a >= b
    if op == "lt":
        return a < b
    if op == "lte":
        return a <= b
    return a == b


def evaluate(
    row: ScreenRow,
    filters: list[Filter],
    sector_medians: dict[str, dict[str, Decimal]],
) -> bool:
    for f in filters:
        if f.metric in ("market_cap", "beta"):
            val = getattr(row, f.metric, None)
        else:
            val = row.metrics.get(f.metric)
        if val is None:
            return False
        target = f.value
        if f.vs_sector:
            sec_map = sector_medians.get(row.sector or "", {})
            sec_val = sec_map.get(f.metric)
            if sec_val is None or sec_val == 0:
                return False
            target = sec_val * f.value
        if not _cmp(val, f.op, target):
            return False
    return True
