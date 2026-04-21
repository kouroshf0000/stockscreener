from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.comps.engine import run_comps
from backend.exports.pdf_memo import build_pdf
from backend.exports.xlsx_writer import build_xlsx
from backend.nlp.risk_analyzer import analyze_risk
from backend.valuation.engine import valuate

router = APIRouter(prefix="/api/v1", tags=["exports"])
EXPORTS_DIR = Path("exports")


@router.get("/export/xlsx/{ticker}")
async def export_xlsx(ticker: str) -> FileResponse:
    sym = ticker.upper()
    try:
        val = await valuate(sym)
        comps = await run_comps(sym)
        risk = await analyze_risk(sym)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    path = EXPORTS_DIR / f"{sym}_{date.today().isoformat()}.xlsx"
    build_xlsx(path, val, comps, risk)
    return FileResponse(path, filename=path.name, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/export/pdf/{ticker}")
async def export_pdf(ticker: str) -> FileResponse:
    sym = ticker.upper()
    try:
        val = await valuate(sym)
        comps = await run_comps(sym)
        risk = await analyze_risk(sym)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    path = EXPORTS_DIR / f"{sym}_memo_{date.today().isoformat()}.pdf"
    build_pdf(path, val, comps, risk)
    return FileResponse(path, filename=path.name, media_type="application/pdf")
