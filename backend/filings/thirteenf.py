from __future__ import annotations

import csv
import io
import re
import zipfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from html import unescape
from urllib.parse import urljoin

from pydantic import BaseModel, ConfigDict, Field

from backend.app.cache import get_redis
from backend.app.config import get_settings
from backend.data_providers.cache import key
from backend.filings.fetcher import http

DATASETS_URL = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"

_ANCHOR_RE = re.compile(
    r'<a[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<label>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


class ThirteenFDatasetLink(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    url: str


class ThirteenFWatchlistManager(BaseModel):
    model_config = ConfigDict(frozen=True)

    slug: str
    name: str
    aliases: tuple[str, ...]


class ThirteenFPositionDigest(BaseModel):
    model_config = ConfigDict(frozen=True)

    issuer: str
    cusip: str
    value: Decimal
    shares: Decimal
    share_type: str
    put_call: str | None = None
    weight_pct: Decimal


class ThirteenFPositionChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    issuer: str
    cusip: str
    current_value: Decimal
    previous_value: Decimal
    delta_value: Decimal
    current_weight_pct: Decimal
    previous_weight_pct: Decimal
    delta_weight_pct: Decimal
    shares_change_pct: Decimal | None = None  # (current - prev) / prev shares


class ThirteenFManagerDigest(BaseModel):
    model_config = ConfigDict(frozen=True)

    manager_slug: str
    manager_name: str
    matched_filing_manager: str
    cik: str
    accession: str
    form: str
    filing_date: date
    period_of_report: date
    filing_lag_days: int | None = None
    is_amendment: bool = False
    holdings_count: int
    portfolio_value: Decimal
    top_1_concentration_pct: Decimal
    top_5_concentration_pct: Decimal
    top_10_concentration_pct: Decimal
    top_holdings: list[ThirteenFPositionDigest]
    new_positions: list[ThirteenFPositionDigest]
    exited_positions: list[ThirteenFPositionDigest]
    biggest_increases: list[ThirteenFPositionChange]
    biggest_decreases: list[ThirteenFPositionChange]
    notes: list[str] = Field(default_factory=list)


class ThirteenFHedgeFundDigestResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_url: str
    latest_dataset_label: str
    previous_dataset_label: str | None = None
    tracked_managers: int
    returned_managers: int
    unmatched_managers: list[str]
    managers: list[ThirteenFManagerDigest]


@dataclass(frozen=True)
class _ManagerCandidate:
    accession: str
    cik: str
    manager_name: str
    form: str
    filing_date: date
    period_of_report: date
    table_value_total: Decimal
    table_entry_total: int


@dataclass(frozen=True)
class _Holding:
    issuer: str
    cusip: str
    value: Decimal
    shares: Decimal
    share_type: str
    put_call: str | None


type TSVRow = dict[str, str]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _normalize(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()


def _decimal(raw: str | None) -> Decimal:
    if raw is None:
        return Decimal("0")
    cleaned = raw.replace(",", "").strip()
    return Decimal(cleaned or "0")


def _int(raw: str | None) -> int:
    return int(_decimal(raw))


def _sec_date(raw: str) -> date:
    return datetime.strptime(raw.strip(), "%d-%b-%Y").date()


def _clean_label(text: str) -> str:
    no_tags = _TAG_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", unescape(no_tags)).strip()


WATCHLIST: tuple[ThirteenFWatchlistManager, ...] = tuple(
    ThirteenFWatchlistManager(slug=_slug(name), name=name, aliases=aliases)
    for name, aliases in [
        ("Bridgewater Associates", ("BRIDGEWATER ASSOCIATES",)),
        ("Renaissance Technologies", ("RENAISSANCE TECHNOLOGIES",)),
        ("Citadel Advisors", ("CITADEL ADVISORS", "CITADEL ADVISORS LLC")),
        ("Millennium Management", ("MILLENNIUM MANAGEMENT", "MILLENNIUM MANAGEMENT LLC")),
        ("D. E. Shaw", ("D E SHAW", "D. E. SHAW", "DE SHAW")),
        ("Elliott Investment Management", ("ELLIOTT INVESTMENT MANAGEMENT", "ELLIOTT MANAGEMENT")),
        ("Point72 Asset Management", ("POINT72", "POINT72 ASSET MANAGEMENT")),
        ("Two Sigma Investments", ("TWO SIGMA INVESTMENTS", "TWO SIGMA")),
        ("Pershing Square Capital Management", ("PERSHING SQUARE",)),
        ("Appaloosa Management", ("APPALOOSA MANAGEMENT",)),
        ("Third Point", ("THIRD POINT",)),
        ("The Baupost Group", ("BAUPOST", "THE BAUPOST GROUP")),
        ("Farallon Capital Management", ("FARALLON",)),
        ("Viking Global Investors", ("VIKING GLOBAL", "VIKING GLOBAL INVESTORS")),
        ("Coatue Management", ("COATUE", "COATUE MANAGEMENT")),
        ("Lone Pine Capital", ("LONE PINE",)),
        ("Tiger Global Management", ("TIGER GLOBAL",)),
        ("Scion Asset Management", ("SCION ASSET MANAGEMENT", "SCION")),
        ("Greenlight Capital", ("GREENLIGHT CAPITAL", "GREENLIGHT")),
        ("Duquesne Family Office", ("DUQUESNE FAMILY OFFICE", "DUQUESNE")),
        ("Soroban Capital Partners", ("SOROBAN", "SOROBAN CAPITAL")),
        ("Trian Fund Management", ("TRIAN", "TRIAN FUND MANAGEMENT")),
        ("JANA Partners", ("JANA PARTNERS", "JANA")),
        ("Maverick Capital", ("MAVERICK CAPITAL", "MAVERICK")),
        ("Glenview Capital Management", ("GLENVIEW CAPITAL", "GLENVIEW")),
    ]
)


async def fetch_dataset_catalog() -> list[ThirteenFDatasetLink]:
    response = await http().get(DATASETS_URL)
    response.raise_for_status()
    links: list[ThirteenFDatasetLink] = []
    seen: set[str] = set()
    for match in _ANCHOR_RE.finditer(response.text):
        href = match.group("href")
        label = _clean_label(match.group("label"))
        if "13F" not in label.upper() or not href.lower().endswith(".zip"):
            continue
        absolute = urljoin(DATASETS_URL, href)
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append(ThirteenFDatasetLink(label=label, url=absolute))
    return links


async def _fetch_zip_bytes(url: str) -> bytes:
    response = await http().get(url)
    response.raise_for_status()
    return response.content


def _read_tsv(zf: zipfile.ZipFile, stem: str) -> list[TSVRow]:
    for name in zf.namelist():
        lower = name.lower()
        if lower.endswith(".tsv") and stem.lower() in lower:
            with zf.open(name) as handle:
                wrapper = io.TextIOWrapper(handle, encoding="utf-8")
                try:
                    return [dict(row) for row in csv.DictReader(wrapper, delimiter="\t")]
                finally:
                    wrapper.close()
    raise FileNotFoundError(f"missing {stem} table in dataset archive")


def _combine_candidates(zip_bytes: bytes) -> list[_ManagerCandidate]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        submissions = {row["ACCESSION_NUMBER"]: row for row in _read_tsv(zf, "submission")}
        cover = {row["ACCESSION_NUMBER"]: row for row in _read_tsv(zf, "coverpage")}
        summary = {row["ACCESSION_NUMBER"]: row for row in _read_tsv(zf, "summarypage")}

    candidates: list[_ManagerCandidate] = []
    for accession, sub in submissions.items():
        submission_type = (sub.get("SUBMISSIONTYPE") or "").strip().upper()
        if submission_type not in {"13F-HR", "13F-HR/A"}:
            continue
        cover_row = cover.get(accession)
        summary_row = summary.get(accession)
        if cover_row is None or summary_row is None:
            continue
        manager_name = (cover_row.get("FILINGMANAGER_NAME") or "").strip()
        if not manager_name:
            continue
        candidates.append(
            _ManagerCandidate(
                accession=accession,
                cik=(sub.get("CIK") or "").zfill(10),
                manager_name=manager_name,
                form=submission_type,
                filing_date=_sec_date(sub["FILING_DATE"]),
                period_of_report=_sec_date(sub["PERIODOFREPORT"]),
                table_value_total=_decimal(summary_row.get("TABLEVALUETOTAL")),
                table_entry_total=_int(summary_row.get("TABLEENTRYTOTAL")),
            )
        )
    return candidates


def _match_score(manager_name: str, watchlist: ThirteenFWatchlistManager) -> int:
    normalized_name = _normalize(manager_name)
    best = -1
    for alias in watchlist.aliases:
        normalized_alias = _normalize(alias)
        if normalized_name == normalized_alias:
            best = max(best, 300)
        elif normalized_name.startswith(normalized_alias):
            best = max(best, 200)
        elif normalized_alias in normalized_name:
            best = max(best, 100)
    return best


def _select_watchlist_candidates(
    candidates: list[_ManagerCandidate],
    watchlist: tuple[ThirteenFWatchlistManager, ...],
    limit: int,
) -> tuple[dict[str, _ManagerCandidate], list[str]]:
    selected: dict[str, _ManagerCandidate] = {}
    unmatched: list[str] = []
    for manager in watchlist[:limit]:
        matches = [
            (candidate, _match_score(candidate.manager_name, manager))
            for candidate in candidates
        ]
        matches = [(candidate, score) for candidate, score in matches if score >= 0]
        if not matches:
            unmatched.append(manager.name)
            continue
        matches.sort(
            key=lambda item: (
                item[1],
                item[0].table_value_total,
                item[0].filing_date,
                item[0].accession,
            ),
            reverse=True,
        )
        selected[manager.slug] = matches[0][0]
    return selected, unmatched


def _load_holdings(zip_bytes: bytes, accessions: set[str]) -> dict[str, list[_Holding]]:
    if not accessions:
        return {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        rows = _read_tsv(zf, "infotable")

    holdings: dict[str, list[_Holding]] = {accession: [] for accession in accessions}
    for row in rows:
        accession = row.get("ACCESSION_NUMBER", "")
        if accession not in accessions:
            continue
        holdings[accession].append(
            _Holding(
                issuer=(row.get("NAMEOFISSUER") or "").strip(),
                cusip=(row.get("CUSIP") or "").strip(),
                value=_decimal(row.get("VALUE")),
                shares=_decimal(row.get("SSHPRNAMT")),
                share_type=(row.get("SSHPRNAMTTYPE") or "").strip(),
                put_call=((row.get("PUTCALL") or "").strip() or None),
            )
        )
    for accession in holdings:
        holdings[accession].sort(key=lambda item: item.value, reverse=True)
    return holdings


def _position_digest(holding: _Holding, total: Decimal) -> ThirteenFPositionDigest:
    weight_pct = Decimal("0")
    if total > 0:
        weight_pct = (holding.value / total) * Decimal("100")
    return ThirteenFPositionDigest(
        issuer=holding.issuer,
        cusip=holding.cusip,
        value=holding.value,
        shares=holding.shares,
        share_type=holding.share_type,
        put_call=holding.put_call,
        weight_pct=weight_pct.quantize(Decimal("0.01")),
    )


def _concentration(holdings: list[_Holding], total: Decimal, n: int) -> Decimal:
    if total <= 0:
        return Decimal("0.00")
    subtotal = sum((holding.value for holding in holdings[:n]), Decimal("0"))
    return ((subtotal / total) * Decimal("100")).quantize(Decimal("0.01"))


def _holdings_by_key(holdings: list[_Holding]) -> dict[str, _Holding]:
    return {f"{holding.cusip}|{holding.issuer.upper()}": holding for holding in holdings}


def _changes(
    current: list[_Holding],
    previous: list[_Holding],
    current_total: Decimal,
    previous_total: Decimal,
) -> tuple[
    list[ThirteenFPositionDigest],
    list[ThirteenFPositionDigest],
    list[ThirteenFPositionChange],
    list[ThirteenFPositionChange],
]:
    current_map = _holdings_by_key(current)
    previous_map = _holdings_by_key(previous)

    new_positions = [
        _position_digest(holding, current_total)
        for key, holding in current_map.items()
        if key not in previous_map
    ]
    exited_positions = [
        _position_digest(holding, previous_total)
        for key, holding in previous_map.items()
        if key not in current_map
    ]

    deltas: list[ThirteenFPositionChange] = []
    for position_key, holding in current_map.items():
        prior = previous_map.get(position_key)
        if prior is None:
            continue
        current_weight = (
            Decimal("0")
            if current_total <= 0
            else (holding.value / current_total) * Decimal("100")
        )
        previous_weight = (
            Decimal("0")
            if previous_total <= 0
            else (prior.value / previous_total) * Decimal("100")
        )
        curr_shares = holding.shares
        prev_shares = prior.shares
        shares_change_pct = (
            (curr_shares - prev_shares) / prev_shares
            if prev_shares
            else None
        )
        deltas.append(
            ThirteenFPositionChange(
                issuer=holding.issuer,
                cusip=holding.cusip,
                current_value=holding.value,
                previous_value=prior.value,
                delta_value=holding.value - prior.value,
                current_weight_pct=current_weight.quantize(Decimal("0.01")),
                previous_weight_pct=previous_weight.quantize(Decimal("0.01")),
                delta_weight_pct=(current_weight - previous_weight).quantize(Decimal("0.01")),
                shares_change_pct=shares_change_pct,
            )
        )

    deltas.sort(key=lambda item: item.delta_value, reverse=True)
    new_positions.sort(key=lambda item: item.value, reverse=True)
    exited_positions.sort(key=lambda item: item.value, reverse=True)
    biggest_increases = [item for item in deltas if item.delta_value > 0][:5]
    biggest_decreases = sorted(
        [item for item in deltas if item.delta_value < 0],
        key=lambda item: item.delta_value,
    )[:5]
    return new_positions[:5], exited_positions[:5], biggest_increases, biggest_decreases


def _build_digest(
    manager: ThirteenFWatchlistManager,
    current_candidate: _ManagerCandidate,
    current_holdings: list[_Holding],
    previous_candidate: _ManagerCandidate | None,
    previous_holdings: list[_Holding],
    top_positions: int,
) -> ThirteenFManagerDigest:
    current_total = current_candidate.table_value_total or sum(
        (holding.value for holding in current_holdings),
        Decimal("0"),
    )
    previous_total = (
        previous_candidate.table_value_total
        if previous_candidate is not None
        else sum((holding.value for holding in previous_holdings), Decimal("0"))
    )
    new_positions, exited_positions, biggest_increases, biggest_decreases = _changes(
        current_holdings,
        previous_holdings,
        current_total,
        previous_total,
    )
    filing_lag_days = (
        (current_candidate.filing_date - current_candidate.period_of_report).days
        if current_candidate.filing_date is not None and current_candidate.period_of_report is not None
        else None
    )
    is_amendment = current_candidate.form == "13F-HR/A"
    notes: list[str] = []
    if previous_candidate is None:
        notes.append("No prior-quarter filing match in the tracked SEC 13F dataset.")
    if current_candidate.manager_name.upper() != manager.name.upper():
        notes.append(f"Matched SEC filing manager name: {current_candidate.manager_name}.")
    return ThirteenFManagerDigest(
        manager_slug=manager.slug,
        manager_name=manager.name,
        matched_filing_manager=current_candidate.manager_name,
        cik=current_candidate.cik,
        accession=current_candidate.accession,
        form=current_candidate.form,
        filing_date=current_candidate.filing_date,
        period_of_report=current_candidate.period_of_report,
        filing_lag_days=filing_lag_days,
        is_amendment=is_amendment,
        holdings_count=current_candidate.table_entry_total or len(current_holdings),
        portfolio_value=current_total,
        top_1_concentration_pct=_concentration(current_holdings, current_total, 1),
        top_5_concentration_pct=_concentration(current_holdings, current_total, 5),
        top_10_concentration_pct=_concentration(current_holdings, current_total, 10),
        top_holdings=[
            _position_digest(holding, current_total)
            for holding in current_holdings[:top_positions]
        ],
        new_positions=new_positions,
        exited_positions=exited_positions,
        biggest_increases=biggest_increases,
        biggest_decreases=biggest_decreases,
        notes=notes,
    )


async def _supabase_cache_get(latest_label: str) -> ThirteenFHedgeFundDigestResponse | None:
    """Return cached digest from Supabase, or None on miss/error."""
    try:
        from backend.app.supabase_client import get_supabase
        resp = await asyncio.to_thread(
            lambda: get_supabase()
            .table("thirteenf_digest_cache")
            .select("payload")
            .eq("latest_label", latest_label)
            .limit(1)
            .execute()
        )
        if resp.data:
            return ThirteenFHedgeFundDigestResponse.model_validate(resp.data[0]["payload"])
    except Exception:
        pass
    return None


async def _supabase_cache_set(latest_label: str, response: ThirteenFHedgeFundDigestResponse) -> None:
    """Upsert digest into Supabase cache. Fire-and-forget."""
    try:
        import json
        from backend.app.supabase_client import get_supabase
        await asyncio.to_thread(
            lambda: get_supabase()
            .table("thirteenf_digest_cache")
            .upsert({"latest_label": latest_label, "payload": json.loads(response.model_dump_json())})
            .execute()
        )
    except Exception:
        pass


async def fetch_hedge_fund_digests(
    limit: int = 25,
    top_positions: int = 10,
) -> ThirteenFHedgeFundDigestResponse:
    catalog = await fetch_dataset_catalog()
    dataset_links = catalog[:2]
    if not dataset_links:
        raise LookupError("SEC 13F dataset catalog returned no ZIP files")

    latest = dataset_links[0]
    previous = dataset_links[1] if len(dataset_links) > 1 else None

    # Supabase cache: avoids downloading 18MB of ZIPs on every pipeline run
    cached = await _supabase_cache_get(latest.label)
    if cached is not None:
        return cached

    redis_key = key(
        "edgar",
        "13f",
        latest.label,
        previous.label if previous else "none",
        str(limit),
        str(top_positions),
    )
    redis = get_redis()
    if redis is not None:
        try:
            cached_redis = await redis.get(redis_key)
            if cached_redis:
                return ThirteenFHedgeFundDigestResponse.model_validate_json(cached_redis)
        except Exception:
            pass

    latest_zip = await _fetch_zip_bytes(latest.url)
    latest_candidates = _combine_candidates(latest_zip)
    tracked_watchlist = WATCHLIST[:limit]
    selected_latest, unmatched = _select_watchlist_candidates(latest_candidates, WATCHLIST, limit)

    previous_selected: dict[str, _ManagerCandidate] = {}
    previous_holdings: dict[str, list[_Holding]] = {}
    previous_label: str | None = None
    if previous is not None:
        previous_label = previous.label
        previous_zip = await _fetch_zip_bytes(previous.url)
        previous_candidates = _combine_candidates(previous_zip)
        previous_selected, _ = _select_watchlist_candidates(previous_candidates, WATCHLIST, limit)
        previous_holdings = _load_holdings(
            previous_zip,
            {candidate.accession for candidate in previous_selected.values()},
        )

    latest_holdings = _load_holdings(
        latest_zip,
        {candidate.accession for candidate in selected_latest.values()},
    )

    digests: list[ThirteenFManagerDigest] = []
    for manager in tracked_watchlist:
        current_candidate = selected_latest.get(manager.slug)
        if current_candidate is None:
            continue
        digests.append(
            _build_digest(
                manager=manager,
                current_candidate=current_candidate,
                current_holdings=latest_holdings.get(current_candidate.accession, []),
                previous_candidate=previous_selected.get(manager.slug),
                previous_holdings=(
                    previous_holdings.get(previous_selected[manager.slug].accession, [])
                    if manager.slug in previous_selected
                    else []
                ),
                top_positions=top_positions,
            )
        )

    response = ThirteenFHedgeFundDigestResponse(
        source_url=DATASETS_URL,
        latest_dataset_label=latest.label,
        previous_dataset_label=previous_label,
        tracked_managers=limit,
        returned_managers=len(digests),
        unmatched_managers=unmatched,
        managers=digests,
    )
    if redis is not None:
        with suppress(Exception):
            await redis.set(
                redis_key,
                response.model_dump_json(),
                ex=get_settings().cache_ttl_fundamentals_s,
            )
    # Persist to Supabase so future pipeline runs skip the ZIP download entirely
    await _supabase_cache_set(latest.label, response)
    return response


async def fetch_holders_for_ticker(
    cusip: str,
    quarters: int = 2,
) -> list[dict]:
    """Return watchlist managers holding this CUSIP, with their position details."""
    digest_response = await fetch_hedge_fund_digests()

    # Build a lookup of shares_change_pct from position change lists per manager
    def _find_change_pct(manager_digest: ThirteenFManagerDigest, target_cusip: str) -> Decimal | None:
        for change in manager_digest.biggest_increases + manager_digest.biggest_decreases:
            if change.cusip == target_cusip:
                return change.shares_change_pct
        return None

    results: list[dict] = []
    for manager_digest in digest_response.managers:
        for holding in manager_digest.top_holdings:
            if holding.cusip == cusip:
                results.append(
                    {
                        "manager": manager_digest.manager_name,
                        "shares": holding.shares,
                        "value_thousands": holding.value,
                        "weight_pct": holding.weight_pct,
                        "put_call": holding.put_call,
                        "shares_change_pct": _find_change_pct(manager_digest, cusip),
                    }
                )
                break  # one entry per manager

    return results
