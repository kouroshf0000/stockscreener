from __future__ import annotations

from pathlib import PurePosixPath
from typing import NamedTuple

from backend.data_providers.models import FilingRef
from backend.filings.discovery import list_filings
from backend.filings.extractor import extract_risk_factors
from backend.filings.fetcher import fetch_document, fetch_index, rank_candidate_docs
from backend.filings.taxonomy import ANNUAL_FORMS, QUARTERLY_FORMS, RISK_FACTOR_FORMS


MIN_CHARS = 1_500
MAX_DOCS_PER_FILING = 6
MAX_FILINGS_TO_TRY = 4


class RiskExtractionTrace(NamedTuple):
    text: str | None
    reason: str
    filing: FilingRef | None
    doc_url: str | None
    chars: int
    attempts: list[dict]


async def _extract_from_filing(filing: FilingRef) -> RiskExtractionTrace:
    attempts: list[dict] = []
    primary_name = PurePosixPath(filing.primary_doc_url).name
    try:
        index = await fetch_index(filing.cik, filing.accession)
    except Exception as e:
        return RiskExtractionTrace(
            None,
            f"index_fetch_failed:{type(e).__name__}",
            filing,
            None,
            0,
            attempts,
        )

    ordered = rank_candidate_docs(index, primary_name)
    if not ordered:
        return RiskExtractionTrace(None, "no_documents_in_index", filing, None, 0, attempts)

    for doc in ordered[:MAX_DOCS_PER_FILING]:
        try:
            body = await fetch_document(doc.url)
        except Exception as e:
            attempts.append({"doc": doc.name, "reason": f"fetch_failed:{type(e).__name__}", "chars": 0})
            continue
        if len(body) < 3_000:
            attempts.append({"doc": doc.name, "reason": "too_small", "chars": len(body)})
            continue
        extraction = extract_risk_factors(filing.form, body)
        attempts.append({"doc": doc.name, "reason": extraction.reason, "chars": extraction.chars})
        if extraction.text and extraction.chars >= MIN_CHARS:
            return RiskExtractionTrace(
                extraction.text,
                "ok",
                filing,
                doc.url,
                extraction.chars,
                attempts,
            )

    return RiskExtractionTrace(None, "section_not_found_in_any_exhibit", filing, None, 0, attempts)


async def fetch_risk_factors_universal(
    ticker: str,
    include_quarterly: bool = False,
) -> RiskExtractionTrace:
    """
    Walk multiple filings + multi-exhibit extraction to achieve high coverage.
    Order of attempts:
      1. Latest annual report (10-K / 20-F / 40-F and amendments) — try up to N most recent.
      2. If include_quarterly: latest 10-Q.
      3. Otherwise: fall back to latest prospectus (S-1 / F-1 / 424B*) with Risk Factors.
    """
    forms_to_try: tuple[str, ...] = ANNUAL_FORMS
    if include_quarterly:
        forms_to_try = (*ANNUAL_FORMS, *QUARTERLY_FORMS)

    filings = await list_filings(ticker, forms=forms_to_try, limit=MAX_FILINGS_TO_TRY)
    all_attempts: list[dict] = []
    last_filing_tried: FilingRef | None = None

    for filing in filings:
        last_filing_tried = filing
        trace = await _extract_from_filing(filing)
        all_attempts.extend({**a, "filing": f"{filing.form}/{filing.accession}"} for a in trace.attempts)
        if trace.text:
            return RiskExtractionTrace(
                trace.text, trace.reason, trace.filing, trace.doc_url, trace.chars, all_attempts
            )

    prospectus_filings = await list_filings(ticker, forms=RISK_FACTOR_FORMS, limit=MAX_FILINGS_TO_TRY)
    for filing in prospectus_filings:
        if filing.form in forms_to_try:
            continue
        last_filing_tried = filing
        trace = await _extract_from_filing(filing)
        all_attempts.extend({**a, "filing": f"{filing.form}/{filing.accession}"} for a in trace.attempts)
        if trace.text:
            return RiskExtractionTrace(
                trace.text, trace.reason, trace.filing, trace.doc_url, trace.chars, all_attempts
            )

    if last_filing_tried is None:
        return RiskExtractionTrace(
            None, "no_risk_factor_filings_found_on_edgar", None, None, 0, all_attempts
        )
    return RiskExtractionTrace(
        None,
        "exhausted_all_filings_and_exhibits",
        last_filing_tried,
        None,
        0,
        all_attempts,
    )
