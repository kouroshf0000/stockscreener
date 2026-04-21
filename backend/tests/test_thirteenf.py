from __future__ import annotations

import io
import zipfile
from datetime import date
from decimal import Decimal

import pytest

from backend.filings import thirteenf


def _dataset_zip(
    *,
    accession: str,
    manager_name: str,
    filing_date: str,
    period_of_report: str,
    total_value: str,
    total_entries: str,
    holdings: list[tuple[str, str, str, str]],
    submission_type: str = "13F-HR",
) -> bytes:
    submission = "\t".join(
        ["ACCESSION_NUMBER", "FILING_DATE", "SUBMISSIONTYPE", "CIK", "PERIODOFREPORT"]
    ) + "\n"
    submission += "\t".join(
        [accession, filing_date, submission_type, "0001423053", period_of_report]
    ) + "\n"

    coverpage = "\t".join(
        ["ACCESSION_NUMBER", "REPORTCALENDARORQUARTER", "FILINGMANAGER_NAME", "REPORTTYPE"]
    ) + "\n"
    coverpage += "\t".join(
        [accession, period_of_report, manager_name, "13F HOLDINGS REPORT"]
    ) + "\n"

    summary = "\t".join(["ACCESSION_NUMBER", "TABLEENTRYTOTAL", "TABLEVALUETOTAL"]) + "\n"
    summary += "\t".join([accession, total_entries, total_value]) + "\n"

    infotable = "\t".join(
        [
            "ACCESSION_NUMBER",
            "INFOTABLE_SK",
            "NAMEOFISSUER",
            "TITLEOFCLASS",
            "CUSIP",
            "VALUE",
            "SSHPRNAMT",
            "SSHPRNAMTTYPE",
            "PUTCALL",
            "INVESTMENTDISCRETION",
            "OTHERMANAGER",
            "VOTING_AUTH_SOLE",
            "VOTING_AUTH_SHARED",
            "VOTING_AUTH_NONE",
        ]
    ) + "\n"
    for idx, (issuer, cusip, value, shares) in enumerate(holdings, start=1):
        infotable += "\t".join(
            [
                accession,
                str(idx),
                issuer,
                "COM",
                cusip,
                value,
                shares,
                "SH",
                "",
                "SOLE",
                "",
                shares,
                "0",
                "0",
            ]
        ) + "\n"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SUBMISSION.tsv", submission)
        zf.writestr("COVERPAGE.tsv", coverpage)
        zf.writestr("SUMMARYPAGE.tsv", summary)
        zf.writestr("INFOTABLE.tsv", infotable)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_fetch_hedge_fund_digests_builds_position_and_delta_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    latest_zip = _dataset_zip(
        accession="0001423053-26-000001",
        manager_name="Bridgewater Associates, LP",
        filing_date="15-Feb-2026",
        period_of_report="31-Dec-2025",
        total_value="1000",
        total_entries="3",
        holdings=[
            ("Apple Inc", "037833100", "500", "10"),
            ("Microsoft Corp", "594918104", "300", "5"),
            ("NVIDIA Corp", "67066G104", "200", "4"),
        ],
    )
    previous_zip = _dataset_zip(
        accession="0001423053-25-000099",
        manager_name="Bridgewater Associates, LP",
        filing_date="15-Nov-2025",
        period_of_report="30-Sep-2025",
        total_value="900",
        total_entries="3",
        holdings=[
            ("Apple Inc", "037833100", "400", "8"),
            ("Amazon.com Inc", "023135106", "300", "6"),
            ("Microsoft Corp", "594918104", "200", "3"),
        ],
    )

    async def _catalog() -> list[thirteenf.ThirteenFDatasetLink]:
        return [
            thirteenf.ThirteenFDatasetLink(
                label="2025 December 2026 January February 13F",
                url="latest.zip",
            ),
            thirteenf.ThirteenFDatasetLink(
                label="2025 September October November 13F",
                url="previous.zip",
            ),
        ]

    async def _zip_bytes(url: str) -> bytes:
        if url == "latest.zip":
            return latest_zip
        if url == "previous.zip":
            return previous_zip
        raise AssertionError(url)

    monkeypatch.setattr(thirteenf, "fetch_dataset_catalog", _catalog)
    monkeypatch.setattr(thirteenf, "_fetch_zip_bytes", _zip_bytes)
    monkeypatch.setattr(thirteenf, "WATCHLIST", thirteenf.WATCHLIST[:1])

    result = await thirteenf.fetch_hedge_fund_digests(limit=1, top_positions=2)

    assert result.returned_managers == 1
    assert result.unmatched_managers == []
    manager = result.managers[0]
    assert manager.manager_name == "Bridgewater Associates"
    assert manager.matched_filing_manager == "Bridgewater Associates, LP"
    assert manager.portfolio_value == Decimal("1000")
    assert manager.holdings_count == 3
    assert manager.top_1_concentration_pct == Decimal("50.00")
    assert [holding.issuer for holding in manager.top_holdings] == ["Apple Inc", "Microsoft Corp"]
    assert [holding.issuer for holding in manager.new_positions] == ["NVIDIA Corp"]
    assert [holding.issuer for holding in manager.exited_positions] == ["Amazon.com Inc"]
    assert manager.biggest_increases[0].issuer == "Apple Inc"
    assert manager.biggest_increases[0].delta_value == Decimal("100")
    assert manager.notes == ["Matched SEC filing manager name: Bridgewater Associates, LP."]


@pytest.mark.asyncio
async def test_shares_change_pct_computed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """shares_change_pct is computed and non-None when shares differ across quarters."""
    latest_zip = _dataset_zip(
        accession="0001423053-26-000010",
        manager_name="Bridgewater Associates, LP",
        filing_date="15-Feb-2026",
        period_of_report="31-Dec-2025",
        total_value="1000",
        total_entries="1",
        holdings=[
            ("Apple Inc", "037833100", "500", "20"),  # shares went from 8 -> 20
        ],
    )
    previous_zip = _dataset_zip(
        accession="0001423053-25-000010",
        manager_name="Bridgewater Associates, LP",
        filing_date="15-Nov-2025",
        period_of_report="30-Sep-2025",
        total_value="400",
        total_entries="1",
        holdings=[
            ("Apple Inc", "037833100", "400", "8"),
        ],
    )

    async def _catalog() -> list[thirteenf.ThirteenFDatasetLink]:
        return [
            thirteenf.ThirteenFDatasetLink(label="Q4 2025", url="latest.zip"),
            thirteenf.ThirteenFDatasetLink(label="Q3 2025", url="previous.zip"),
        ]

    async def _zip_bytes(url: str) -> bytes:
        return latest_zip if url == "latest.zip" else previous_zip

    monkeypatch.setattr(thirteenf, "fetch_dataset_catalog", _catalog)
    monkeypatch.setattr(thirteenf, "_fetch_zip_bytes", _zip_bytes)
    monkeypatch.setattr(thirteenf, "WATCHLIST", thirteenf.WATCHLIST[:1])

    result = await thirteenf.fetch_hedge_fund_digests(limit=1, top_positions=1)
    manager = result.managers[0]
    assert manager.biggest_increases, "Expected an increase entry for Apple"
    apple_change = manager.biggest_increases[0]
    assert apple_change.issuer == "Apple Inc"
    assert apple_change.shares_change_pct is not None
    # (20 - 8) / 8 = 1.5
    assert apple_change.shares_change_pct == Decimal("1.5")


@pytest.mark.asyncio
async def test_filing_lag_and_amendment_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """filing_lag_days = filing_date - period_of_report; is_amendment=True for 13F-HR/A."""
    # Use an amendment filing: filed 15-Feb-2026, period ended 31-Dec-2025 → 46 days
    latest_zip = _dataset_zip(
        accession="0001423053-26-000020",
        manager_name="Bridgewater Associates, LP",
        filing_date="15-Feb-2026",
        period_of_report="31-Dec-2025",
        total_value="1000",
        total_entries="1",
        holdings=[("Apple Inc", "037833100", "1000", "10")],
        submission_type="13F-HR/A",
    )

    async def _catalog() -> list[thirteenf.ThirteenFDatasetLink]:
        return [thirteenf.ThirteenFDatasetLink(label="Q4 2025 Amendment", url="latest.zip")]

    async def _zip_bytes(url: str) -> bytes:
        return latest_zip

    monkeypatch.setattr(thirteenf, "fetch_dataset_catalog", _catalog)
    monkeypatch.setattr(thirteenf, "_fetch_zip_bytes", _zip_bytes)
    monkeypatch.setattr(thirteenf, "WATCHLIST", thirteenf.WATCHLIST[:1])

    result = await thirteenf.fetch_hedge_fund_digests(limit=1, top_positions=1)
    manager = result.managers[0]

    expected_lag = (date(2026, 2, 15) - date(2025, 12, 31)).days
    assert manager.filing_lag_days == expected_lag
    assert manager.is_amendment is True


@pytest.mark.asyncio
async def test_holders_for_ticker_reverse_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fetch_holders_for_ticker returns correct manager for matching CUSIP."""
    target_cusip = "037833100"

    # Build a fake digest response to monkeypatch fetch_hedge_fund_digests
    fake_digest = thirteenf.ThirteenFManagerDigest(
        manager_slug="bridgewater-associates",
        manager_name="Bridgewater Associates",
        matched_filing_manager="Bridgewater Associates, LP",
        cik="0001423053",
        accession="0001423053-26-000001",
        form="13F-HR",
        filing_date=date(2026, 2, 15),
        period_of_report=date(2025, 12, 31),
        filing_lag_days=46,
        is_amendment=False,
        holdings_count=2,
        portfolio_value=Decimal("1000"),
        top_1_concentration_pct=Decimal("50.00"),
        top_5_concentration_pct=Decimal("100.00"),
        top_10_concentration_pct=Decimal("100.00"),
        top_holdings=[
            thirteenf.ThirteenFPositionDigest(
                issuer="Apple Inc",
                cusip=target_cusip,
                value=Decimal("500"),
                shares=Decimal("20"),
                share_type="SH",
                put_call=None,
                weight_pct=Decimal("50.00"),
            ),
            thirteenf.ThirteenFPositionDigest(
                issuer="Microsoft Corp",
                cusip="594918104",
                value=Decimal("500"),
                shares=Decimal("10"),
                share_type="SH",
                put_call=None,
                weight_pct=Decimal("50.00"),
            ),
        ],
        new_positions=[],
        exited_positions=[],
        biggest_increases=[
            thirteenf.ThirteenFPositionChange(
                issuer="Apple Inc",
                cusip=target_cusip,
                current_value=Decimal("500"),
                previous_value=Decimal("400"),
                delta_value=Decimal("100"),
                current_weight_pct=Decimal("50.00"),
                previous_weight_pct=Decimal("44.44"),
                delta_weight_pct=Decimal("5.56"),
                shares_change_pct=Decimal("1.5"),
            )
        ],
        biggest_decreases=[],
        notes=[],
    )
    fake_response = thirteenf.ThirteenFHedgeFundDigestResponse(
        source_url="https://example.com",
        latest_dataset_label="Q4 2025",
        previous_dataset_label=None,
        tracked_managers=1,
        returned_managers=1,
        unmatched_managers=[],
        managers=[fake_digest],
    )

    async def _fake_digests(**kwargs: object) -> thirteenf.ThirteenFHedgeFundDigestResponse:
        return fake_response

    monkeypatch.setattr(thirteenf, "fetch_hedge_fund_digests", _fake_digests)

    holders = await thirteenf.fetch_holders_for_ticker(target_cusip, quarters=1)
    assert len(holders) == 1
    h = holders[0]
    assert h["manager"] == "Bridgewater Associates"
    assert h["shares"] == Decimal("20")
    assert h["value_thousands"] == Decimal("500")
    assert h["weight_pct"] == Decimal("50.00")
    assert h["put_call"] is None
    assert h["shares_change_pct"] == Decimal("1.5")
