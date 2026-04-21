from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

ScoutName = Literal["value", "quality", "momentum", "catalyst"]
GateResult = Literal["pass", "fail"]


class ScoutScore(BaseModel):
    model_config = ConfigDict(frozen=True)
    scout: ScoutName
    score: Decimal
    evidence: list[str]


class GateCheck(BaseModel):
    model_config = ConfigDict(frozen=True)
    rule: str
    result: GateResult
    detail: str


class HunterPick(BaseModel):
    model_config = ConfigDict(frozen=True)
    ticker: str
    pick_date: date
    pick_price: Decimal | None
    target_price: Decimal | None
    upside_pct: Decimal | None
    composite_score: Decimal
    scout_scores: list[ScoutScore]
    gate_checks: list[GateCheck]
    gate_passed: bool
    thesis_bullets: list[str]
    deliverables: dict[str, str] = {}


class HunterRunReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: str
    started_at: datetime
    finished_at: datetime
    candidates_evaluated: int
    picks: list[HunterPick]
    rejected: list[HunterPick]
