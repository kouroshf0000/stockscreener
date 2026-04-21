from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from backend.hunter.models import HunterPick, HunterRunReport

LEDGER_DIR = Path("hunter_ledger")


def save_run(report: HunterRunReport) -> Path:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    path = LEDGER_DIR / f"run_{report.run_id}.json"
    path.write_text(report.model_dump_json(indent=2))
    return path


def load_all_runs() -> list[HunterRunReport]:
    if not LEDGER_DIR.exists():
        return []
    out: list[HunterRunReport] = []
    for p in sorted(LEDGER_DIR.glob("run_*.json")):
        try:
            out.append(HunterRunReport.model_validate_json(p.read_text()))
        except Exception:
            continue
    return out


def all_picks() -> list[HunterPick]:
    picks: list[HunterPick] = []
    for r in load_all_runs():
        picks.extend(r.picks)
    return picks


def update_mark_to_market(symbol: str, as_of: date, price: float) -> None:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    path = LEDGER_DIR / "marks.jsonl"
    with path.open("a") as fh:
        fh.write(json.dumps({"symbol": symbol, "as_of": as_of.isoformat(), "price": price}) + "\n")
