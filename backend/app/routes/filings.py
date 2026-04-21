from __future__ import annotations

from pathlib import PurePosixPath

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from backend.data_providers.models import FilingRef
from backend.filings.data_audit import DataQualityReport, audit_data_quality
from backend.filings.discovery import list_filings, resolve_cik
from backend.filings.extractor import extract_8k_items, extract_risk_factors, extract_section
from backend.filings.fetcher import fetch_document, fetch_index, rank_candidate_docs
from backend.filings.risk_factors import fetch_risk_factors_universal
from backend.filings.taxonomy import (
    ANNUAL_FORMS,
    CURRENT_FORMS,
    PROFILES,
    PROSPECTUS_FORMS,
    QUARTERLY_FORMS,
    RISK_FACTOR_FORMS,
)
from backend.filings.conviction_signal import ConvictionSignalResponse, run_conviction_signal
from backend.filings.conviction_screener import ConvictionScreenerResponse, run_conviction_screener
from backend.filings.thirteenf import (
    ThirteenFHedgeFundDigestResponse,
    fetch_hedge_fund_digests,
    fetch_holders_for_ticker,
)

router = APIRouter(prefix="/api/v1/filings", tags=["filings"])


class FormInfo(BaseModel):
    model_config = ConfigDict(frozen=True)
    form: str
    description: str
    supports_risk_factors: bool


class SupportedForms(BaseModel):
    model_config = ConfigDict(frozen=True)
    annual: list[str]
    quarterly: list[str]
    current: list[str]
    prospectus: list[str]
    risk_factor_forms: list[str]
    all: list[FormInfo]


@router.get("/forms", response_model=SupportedForms)
async def supported_forms() -> SupportedForms:
    return SupportedForms(
        annual=list(ANNUAL_FORMS),
        quarterly=list(QUARTERLY_FORMS),
        current=list(CURRENT_FORMS),
        prospectus=list(PROSPECTUS_FORMS),
        risk_factor_forms=list(RISK_FACTOR_FORMS),
        all=[
            FormInfo(
                form=p.form,
                description=p.description,
                supports_risk_factors=p.supports_risk_factors,
            )
            for p in PROFILES.values()
        ],
    )


@router.get("/13f/hedge-funds", response_model=ThirteenFHedgeFundDigestResponse)
async def hedge_fund_13f_digest(
    limit: int = 25,
    top_positions: int = 10,
) -> ThirteenFHedgeFundDigestResponse:
    try:
        return await fetch_hedge_fund_digests(limit=limit, top_positions=top_positions)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"13F digest failed: {e}") from e


@router.get("/13f/conviction-screener", response_model=ConvictionScreenerResponse)
async def conviction_screener(
    top_n: int = Query(default=10, ge=1, le=50),
    min_weight_pct: float = Query(default=1.0, ge=0.1, le=20.0),
    min_buyers: int = Query(default=1, ge=1, le=10),
) -> ConvictionScreenerResponse:
    try:
        return await run_conviction_screener(top_n=top_n, min_weight_pct=min_weight_pct, min_buyers=min_buyers, valuation_timeout=30.0)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"conviction screener failed: {e}") from e


@router.get("/13f/conviction-signal", response_model=ConvictionSignalResponse)
async def conviction_signal(
    min_weight_pct: float = Query(default=1.0, ge=0.1, le=20.0),
    min_buyers: int = Query(default=1, ge=1, le=10),
    top_n: int = Query(default=30, ge=1, le=100),
) -> ConvictionSignalResponse:
    try:
        return await run_conviction_signal(min_weight_pct=min_weight_pct, min_buyers=min_buyers, top_n=top_n)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"conviction signal failed: {e}") from e


@router.get("/13f/holders/{cusip}")
async def get_holders_for_cusip(
    cusip: str,
    quarters: int = Query(default=2, ge=1, le=8),
) -> list[dict]:
    try:
        return await fetch_holders_for_ticker(cusip, quarters=quarters)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"13F holders lookup failed: {e}") from e


@router.get("/{ticker}/list", response_model=list[FilingRef])
async def filings_list(
    ticker: str,
    forms: str | None = None,
    limit: int = 20,
) -> list[FilingRef]:
    form_tuple = tuple(f.strip() for f in forms.split(",") if f.strip()) if forms else None
    return await list_filings(ticker, forms=form_tuple, limit=limit)


class RiskExtractionPayload(BaseModel):
    model_config = ConfigDict(frozen=True)
    ticker: str
    text: str | None
    chars: int
    reason: str
    filing: FilingRef | None
    doc_url: str | None
    attempts: list[dict]


@router.get("/{ticker}/risk-factors", response_model=RiskExtractionPayload)
async def filings_risk_factors(
    ticker: str,
    include_quarterly: bool = False,
) -> RiskExtractionPayload:
    trace = await fetch_risk_factors_universal(ticker, include_quarterly=include_quarterly)
    return RiskExtractionPayload(
        ticker=ticker.upper(),
        text=trace.text,
        chars=trace.chars,
        reason=trace.reason,
        filing=trace.filing,
        doc_url=trace.doc_url,
        attempts=trace.attempts,
    )


@router.get("/{ticker}/data-quality", response_model=DataQualityReport)
async def filings_data_quality(ticker: str) -> DataQualityReport:
    try:
        return await audit_data_quality(ticker)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"data quality audit failed: {e}") from e


class EightKBreakdown(BaseModel):
    model_config = ConfigDict(frozen=True)
    ticker: str
    filing: FilingRef | None
    items: dict[str, str]
    attempts: list[dict]


@router.get("/{ticker}/8k-latest", response_model=EightKBreakdown)
async def latest_8k(ticker: str) -> EightKBreakdown:
    filings = await list_filings(ticker, forms=("8-K", "8-K/A"), limit=1)
    if not filings:
        return EightKBreakdown(ticker=ticker.upper(), filing=None, items={}, attempts=[])
    filing = filings[0]
    attempts: list[dict] = []
    try:
        index = await fetch_index(filing.cik, filing.accession)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"index fetch failed: {e}") from e

    primary = PurePosixPath(filing.primary_doc_url).name
    for doc in rank_candidate_docs(index, primary)[:4]:
        try:
            body = await fetch_document(doc.url)
        except Exception as e:
            attempts.append({"doc": doc.name, "error": str(e)})
            continue
        items = extract_8k_items(body)
        if items:
            return EightKBreakdown(
                ticker=ticker.upper(),
                filing=filing,
                items=items,
                attempts=attempts,
            )
        attempts.append({"doc": doc.name, "items_found": 0})
    return EightKBreakdown(ticker=ticker.upper(), filing=filing, items={}, attempts=attempts)


class FilingRawResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    ticker: str
    filing: FilingRef
    primary_text_length: int
    index_documents: list[dict]


@router.get("/{ticker}/{accession}", response_model=FilingRawResponse)
async def get_filing_details(ticker: str, accession: str) -> FilingRawResponse:
    res = await resolve_cik(ticker)
    if res is None:
        raise HTTPException(status_code=404, detail="CIK not found for ticker")
    try:
        index = await fetch_index(res.cik, accession)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    filings = await list_filings(ticker, forms=None, limit=200)
    filing_ref = next((f for f in filings if f.accession == accession), None)
    if filing_ref is None:
        raise HTTPException(status_code=404, detail="filing not found in recent submissions")
    try:
        primary = await fetch_document(filing_ref.primary_doc_url)
    except Exception:
        primary = ""
    return FilingRawResponse(
        ticker=ticker.upper(),
        filing=filing_ref,
        primary_text_length=len(primary),
        index_documents=[
            {"name": d.name, "type": d.type, "url": d.url, "size": d.size}
            for d in index.documents
        ],
    )


class SectionResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    ticker: str
    form: str
    section: str
    text: str | None
    chars: int
    reason: str


@router.get("/{ticker}/section/{section}", response_model=SectionResult)
async def filing_section(ticker: str, section: str, form: str = "10-K") -> SectionResult:
    filings = await list_filings(ticker, forms=(form,), limit=1)
    if not filings:
        raise HTTPException(status_code=404, detail=f"no {form} filing found")
    filing = filings[0]
    from pathlib import PurePosixPath

    from backend.filings.fetcher import rank_candidate_docs

    index = await fetch_index(filing.cik, filing.accession)
    primary = PurePosixPath(filing.primary_doc_url).name
    for doc in rank_candidate_docs(index, primary)[:4]:
        try:
            body = await fetch_document(doc.url)
        except Exception:
            continue
        if section == "risk_factors":
            extraction = extract_risk_factors(form, body)
        else:
            extraction = extract_section(form, section, body)
        if extraction.text:
            return SectionResult(
                ticker=ticker.upper(),
                form=form,
                section=section,
                text=extraction.text,
                chars=extraction.chars,
                reason="ok",
            )
    return SectionResult(
        ticker=ticker.upper(),
        form=form,
        section=section,
        text=None,
        chars=0,
        reason="section_not_found",
    )
