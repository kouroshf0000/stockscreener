from __future__ import annotations

from datetime import date

import pytest

from backend.data_providers import edgar_client
from backend.filings import discovery, fetcher, risk_factors
from backend.filings.fetcher import FilingDocument, FilingIndex


class _Resp:
    def __init__(self, data: object = None, text: str = "") -> None:
        self._data = data
        self.text = text
        self.status_code = 200

    def json(self) -> object:
        return self._data

    def raise_for_status(self) -> None:
        return None


class _FakeHttp:
    def __init__(self, routes: dict[str, _Resp]) -> None:
        self.routes = routes

    async def get(self, url: str, params: dict | None = None) -> _Resp:
        for prefix, resp in self.routes.items():
            if url.startswith(prefix):
                return resp
        raise AssertionError(f"unexpected url: {url}")


def _ticker_map() -> dict:
    return {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "APPLE INC"}}


def _submissions(form: str = "10-K") -> dict:
    return {
        "filings": {
            "recent": {
                "form": [form, "8-K"],
                "accessionNumber": ["0000320193-25-000001", "0000320193-25-000002"],
                "primaryDocument": ["aapl-10k.htm", "aapl-8k.htm"],
                "filingDate": ["2025-11-01", "2025-10-15"],
            }
        }
    }


@pytest.mark.asyncio
async def test_latest_filing_and_risk_factors(monkeypatch: pytest.MonkeyPatch) -> None:
    real_body = (
        "<html><body>"
        "Item 1A. Risk Factors 5  Item 1B. Unresolved Staff Comments 25 "
        "Item 1A. Risk Factors "
        + ("We face supply chain risks and regulatory exposure. " * 200)
        + "Item 1B. Unresolved Staff Comments"
        "</body></html>"
    )
    routes = {
        discovery.TICKER_MAP_URL: _Resp(data=_ticker_map()),
        "https://data.sec.gov/submissions/CIK0000320193.json": _Resp(data=_submissions()),
        "https://www.sec.gov/Archives/edgar/data/320193/000032019325000001/index.json": _Resp(
            data={"directory": {"item": [{"name": "aapl-10k.htm", "type": "10-K", "size": "80000"}]}}
        ),
        "https://www.sec.gov/Archives/edgar/data/320193/000032019325000001/aapl-10k.htm": _Resp(
            text=real_body
        ),
    }
    fake = _FakeHttp(routes)
    monkeypatch.setattr(discovery, "http", lambda: fake)
    monkeypatch.setattr(fetcher, "http", lambda: fake)

    filing = await edgar_client.latest_filing("AAPL", "10-K")
    assert filing is not None
    assert filing.form == "10-K"
    assert filing.accession == "0000320193-25-000001"
    assert "320193" in filing.primary_doc_url

    rf = await edgar_client.fetch_risk_factors("AAPL")
    assert rf is not None
    assert "supply" in rf.lower()
    assert len(rf) > 5000
    assert rf.count("supply") > 5

    diag = await edgar_client.fetch_risk_factors_with_diagnostics("AAPL")
    assert diag.text is not None
    assert diag.reason == "ok"
    assert diag.filing is not None


@pytest.mark.asyncio
async def test_diagnostics_report_missing_section(monkeypatch: pytest.MonkeyPatch) -> None:
    ticker_map = {"0": {"cik_str": 999999, "ticker": "TESTCO", "title": "TEST CO"}}
    submissions = {
        "filings": {
            "recent": {
                "form": ["10-K"],
                "accessionNumber": ["0000999999-25-000001"],
                "primaryDocument": ["test.htm"],
                "filingDate": ["2025-01-01"],
            }
        }
    }
    doc = "<html><body>" + "This filing has no risk factors section at all. " * 500 + "</body></html>"
    routes = {
        discovery.TICKER_MAP_URL: _Resp(data=ticker_map),
        "https://data.sec.gov/submissions/CIK0000999999.json": _Resp(data=submissions),
        "https://www.sec.gov/Archives/edgar/data/999999/000099999925000001/index.json": _Resp(
            data={"directory": {"item": [{"name": "test.htm", "type": "10-K", "size": "30000"}]}}
        ),
        "https://www.sec.gov/Archives/edgar/data/999999/000099999925000001/test.htm": _Resp(text=doc),
    }
    fake = _FakeHttp(routes)
    monkeypatch.setattr(discovery, "http", lambda: fake)
    monkeypatch.setattr(fetcher, "http", lambda: fake)

    diag = await edgar_client.fetch_risk_factors_with_diagnostics("TESTCO")
    assert diag.text is None
    assert diag.reason == "exhausted_all_filings_and_exhibits"
