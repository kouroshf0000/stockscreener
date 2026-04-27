from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.data_providers.models import FilingRef
from backend.filings.fetcher import SUBMISSIONS_URL, TICKER_MAP_URL, http

ARCHIVE_URL_T = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{primary_doc}"

# Module-level cache for the SEC ticker map — one fetch per day, shared across all tickers
_ticker_map_cache: dict | None = None
_ticker_map_date: date | None = None


class CIKResolution(BaseModel):
    model_config = ConfigDict(frozen=True)
    ticker: str
    cik: str
    title: str


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=4))
async def _fetch_ticker_map() -> dict:
    r = await http().get(TICKER_MAP_URL)
    r.raise_for_status()
    return r.json()


async def resolve_cik(ticker: str) -> CIKResolution | None:
    global _ticker_map_cache, _ticker_map_date
    sym = ticker.upper()
    today = date.today()
    if _ticker_map_cache is None or _ticker_map_date != today:
        _ticker_map_cache = await _fetch_ticker_map()
        _ticker_map_date = today
    for _, row in _ticker_map_cache.items():
        if str(row.get("ticker", "")).upper() == sym:
            return CIKResolution(
                ticker=sym,
                cik=f"{int(row['cik_str']):010d}",
                title=row.get("title", sym),
            )
    return None


def _archive_url(cik: str, accession: str, primary_doc: str) -> str:
    return ARCHIVE_URL_T.format(
        cik_int=int(cik),
        acc_nodash=accession.replace("-", ""),
        primary_doc=primary_doc,
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=4))
async def list_filings(
    ticker: str,
    forms: tuple[str, ...] | None = None,
    limit: int = 20,
) -> list[FilingRef]:
    res = await resolve_cik(ticker)
    if res is None:
        return []
    r = await http().get(SUBMISSIONS_URL.format(cik=res.cik))
    r.raise_for_status()
    data = r.json()
    recent = data.get("filings", {}).get("recent", {})
    all_forms = recent.get("form", [])
    out: list[FilingRef] = []
    for i, f in enumerate(all_forms):
        if forms is not None and f not in forms:
            continue
        acc = recent["accessionNumber"][i]
        primary = recent["primaryDocument"][i]
        filed = date.fromisoformat(recent["filingDate"][i])
        out.append(
            FilingRef(
                cik=res.cik,
                accession=acc,
                form=f,
                filed=filed,
                primary_doc_url=_archive_url(res.cik, acc, primary),
            )
        )
        if len(out) >= limit:
            break
    return out


async def latest(ticker: str, forms: tuple[str, ...]) -> FilingRef | None:
    items = await list_filings(ticker, forms=forms, limit=1)
    return items[0] if items else None


async def latest_with_fallbacks(
    ticker: str, form_fallbacks: tuple[str, ...]
) -> list[FilingRef]:
    """Walk through the most recent filings matching any form in fallbacks.
    Returns list ordered most-recent-first, so caller can try each if extraction fails."""
    return await list_filings(ticker, forms=form_fallbacks, limit=8)
