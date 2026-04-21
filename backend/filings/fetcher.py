from __future__ import annotations

import httpx
from pydantic import BaseModel, ConfigDict
from tenacity import retry, stop_after_attempt, wait_exponential

UA = "AlphaArchitect research-tool contact@example.com"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
INDEX_JSON = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/index.json"

_client: httpx.AsyncClient | None = None


def http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"},
            timeout=25,
        )
    return _client


class FilingDocument(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    type: str | None
    url: str
    size: int | None = None


class FilingIndex(BaseModel):
    model_config = ConfigDict(frozen=True)
    cik: str
    accession: str
    documents: list[FilingDocument]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=4))
async def fetch_index(cik: str, accession: str) -> FilingIndex:
    acc_nodash = accession.replace("-", "")
    url = INDEX_JSON.format(cik_int=int(cik), acc_nodash=acc_nodash)
    r = await http().get(url)
    r.raise_for_status()
    data = r.json()
    items = (data.get("directory") or {}).get("item") or []
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_nodash}/"
    docs: list[FilingDocument] = []
    for it in items:
        name = it.get("name")
        if not name:
            continue
        docs.append(
            FilingDocument(
                name=name,
                type=it.get("type"),
                url=base + name,
                size=int(it["size"]) if it.get("size") and str(it["size"]).isdigit() else None,
            )
        )
    return FilingIndex(cik=cik, accession=accession, documents=docs)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=4))
async def fetch_document(url: str) -> str:
    r = await http().get(url)
    r.raise_for_status()
    return r.text


def rank_candidate_docs(
    index: FilingIndex, primary_doc_name: str | None
) -> list[FilingDocument]:
    """
    Order documents by likelihood of containing filing body:
      1. Primary document (if specified).
      2. Largest .htm/.html files (body of 10-K/10-Q/20-F usually largest).
      3. .txt files as last resort (older SGML filings).
    """
    html_docs = [d for d in index.documents if d.name.lower().endswith((".htm", ".html"))]
    txt_docs = [d for d in index.documents if d.name.lower().endswith(".txt")]

    html_docs.sort(key=lambda d: d.size or 0, reverse=True)
    txt_docs.sort(key=lambda d: d.size or 0, reverse=True)

    ordered: list[FilingDocument] = []
    seen: set[str] = set()

    if primary_doc_name:
        for d in index.documents:
            if d.name == primary_doc_name:
                ordered.append(d)
                seen.add(d.name)
                break

    for d in html_docs:
        if d.name not in seen:
            ordered.append(d)
            seen.add(d.name)

    for d in txt_docs:
        if d.name not in seen:
            ordered.append(d)
            seen.add(d.name)

    return ordered
