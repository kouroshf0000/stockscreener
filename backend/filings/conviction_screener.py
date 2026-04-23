from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.filings.conviction_signal import run_conviction_signal
from backend.valuation.engine import valuate

logger = logging.getLogger(__name__)

# 13F issuer names → exchange tickers.
# SEC names are normalised UPPER strings; add entries as new fund positions appear.
ISSUER_TICKER_MAP: dict[str, str] = {
    "AMAZON COM INC": "AMZN",
    "ALPHABET INC": "GOOGL",
    "META PLATFORMS INC": "META",
    "FISERV INC": "FISV",
    "ASML HOLDING NV": "ASML",
    "ASML HOLDING N V": "ASML",  # SEC 13F variant with space
    "VISTRA CORP": "VST",
    "CONSTELLATION ENERGY CORP": "CEG",
    "S&P GLOBAL INC": "SPGI",
    "PHILLIPS 66": "PSX",
    "UNION PACIFIC CORP": "UNP",
    "TRANSDIGM GROUP INC": "TDG",
    "EQUIFAX INC": "EFX",
    "GE AEROSPACE": "GEV",
    "CARVANA CO": "CVNA",
    "MICROSOFT CORP": "MSFT",
    "NVIDIA CORP": "NVDA",
    "APPLE INC": "AAPL",
    "TESLA INC": "TSLA",
    "UNITEDHEALTH GROUP INC": "UNH",
    "MASTERCARD INC": "MA",
    "VISA INC": "V",
    "BERKSHIRE HATHAWAY INC": "BRK-B",
    "BROADCOM INC": "AVGO",
    "ELI LILLY & CO": "LLY",
    "APPLIED MATERIALS INC": "AMAT",
    "VERTIV HOLDINGS CO": "VRT",
    "MOODY'S CORP": "MCO",
    "INTERCONTINENTAL EXCHANGE INC": "ICE",
    "CME GROUP INC": "CME",
    "DANAHER CORP": "DHR",
    "IDEXX LABORATORIES INC": "IDXX",
    "TRANE TECHNOLOGIES PLC": "TT",
    "COSTAR GROUP INC": "CSGP",
    "DATADOG INC": "DDOG",
    "CROWDSTRIKE HOLDINGS INC": "CRWD",
    "WORKDAY INC": "WDAY",
    "SERVICENOW INC": "NOW",
    "SALESFORCE INC": "CRM",
    "ADOBE INC": "ADBE",
    "MOTOROLA SOLUTIONS INC": "MSI",
    "CHARTER COMMUNICATIONS INC": "CHTR",
    "LIBERTY MEDIA CORP": "LSXMA",
    "CONSTELLATION BRANDS INC": "STZ",
    "DOLLAR GENERAL CORP": "DG",
    "DOLLAR TREE INC": "DLTR",
    "BOOKING HOLDINGS INC": "BKNG",
    "AIRBNB INC": "ABNB",
    "UBER TECHNOLOGIES INC": "UBER",
    "LYFT INC": "LYFT",
    "PALANTIR TECHNOLOGIES INC": "PLTR",
    "SNOWFLAKE INC": "SNOW",
    "SHOPIFY INC": "SHOP",
    "PINTEREST INC": "PINS",
    "SPOTIFY TECHNOLOGY SA": "SPOT",
    "DOORDASH INC": "DASH",
    "CARPENTER TECHNOLOGY CORP": "CRS",
    "LULULEMON ATHLETICA INC": "LULU",
    "INTUITIVE SURGICAL INC": "ISRG",
    "ARISTA NETWORKS INC": "ANET",
    "CLOUDFLARE INC": "NET",
    "TRADE DESK INC": "TTD",
    "MONGODB INC": "MDB",
    "COINBASE GLOBAL INC": "COIN",
    "ROBINHOOD MARKETS INC": "HOOD",
    "DUOLINGO INC": "DUOL",
    "AMERICAN EXPRESS CO": "AXP",
    "JPMORGAN CHASE & CO": "JPM",
    "WELLS FARGO & CO": "WFC",
    "BANK OF AMERICA CORP": "BAC",
    "GOLDMAN SACHS GROUP INC": "GS",
    "CHARLES SCHWAB CORP": "SCHW",
    "BLACKSTONE INC": "BX",
    "KKR & CO INC": "KKR",
    "APOLLO GLOBAL MANAGEMENT INC": "APO",
    "INTERACTIVE BROKERS GROUP INC": "IBKR",
    "PALO ALTO NETWORKS INC": "PANW",
    "FORTINET INC": "FTNT",
    "ZSCALER INC": "ZS",
    "SENTINELONE INC": "S",
    "VEEVA SYSTEMS INC": "VEEV",
    "INSULET CORP": "PODD",
    "REGENERON PHARMACEUTICALS INC": "REGN",
    "VERTEX PHARMACEUTICALS INC": "VRTX",
    "GILEAD SCIENCES INC": "GILD",
    "BIOGEN INC": "BIIB",
    "ALNYLAM PHARMACEUTICALS INC": "ALNY",
    "CENCORA INC": "COR",
    "MCKESSON CORP": "MCK",
    "CARDINAL HEALTH INC": "CAH",
    "WASTE MANAGEMENT INC": "WM",
    "REPUBLIC SERVICES INC": "RSG",
    "NEXTGEN ENERGY INC": "NEE",
    "AMERICAN TOWER CORP": "AMT",
    "CROWN CASTLE INC": "CCI",
    "SBA COMMUNICATIONS CORP": "SBAC",
    "PROLOGIS INC": "PLD",
    "SIMON PROPERTY GROUP INC": "SPG",
    "ESTEE LAUDER COMPANIES INC": "EL",
    "COLGATE PALMOLIVE CO": "CL",
    "CHURCH & DWIGHT CO INC": "CHD",
    "ROLLINS INC": "ROL",
    "CINTAS CORP": "CTAS",
    "FASTENAL CO": "FAST",
    "WW GRAINGER INC": "GWW",
}

# ETF/fund keywords — skip these, they carry no stock-specific thesis
_ETF_KEYWORDS = frozenset({
    "SELECT SECTOR SPDR", "SPDR", "ISHARES", "VANGUARD", "INVESCO EXCHANGE",
    "INVESCO QQQ", "PROSHARES", "DIREXION", "FIRST TRUST", "SCHWAB STRATEGIC",
    "WISDOMTREE", "GLOBAL X", "VANECK",
})

ValuationStatus = Literal["ok", "ticker_unresolved", "auditor_blocked", "valuation_error", "timeout"]

# Single global semaphore — all callers (conviction + universe) share it so concurrent
# asyncio.gather runs never issue overlapping yfinance requests (crumb corruption).
_YFINANCE_SEM = asyncio.Semaphore(1)


class ConvictionScreenRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    rank: int
    issuer: str
    ticker: str | None
    conviction_score: Decimal
    buyer_count: int
    buyers: list[str]
    max_weight_pct: Decimal
    is_consensus: bool
    upside_pct: Decimal | None
    implied_price: Decimal | None
    current_price: Decimal | None
    status: ValuationStatus
    source: str = "13f"


class ConvictionScreenerResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    quarter: str
    dataset_label: str
    fundamental_funds_scanned: int
    rows: list[ConvictionScreenRow]
    valuation_ok_count: int
    valuation_failed_count: int


def _is_etf(issuer: str) -> bool:
    upper = issuer.upper()
    return any(kw in upper for kw in _ETF_KEYWORDS)


def _resolve_ticker(issuer: str) -> str | None:
    if _is_etf(issuer):
        return None
    normalised = issuer.strip().upper()
    return ISSUER_TICKER_MAP.get(normalised)


async def _safe_valuate(ticker: str, timeout: float = 30.0, sem: asyncio.Semaphore = _YFINANCE_SEM) -> tuple[Decimal | None, Decimal | None, Decimal | None, ValuationStatus]:
    """Returns (upside_pct, implied_price, current_price, status)."""
    async def _run():
        return await asyncio.wait_for(valuate(ticker, include_overlays=False), timeout=timeout)

    try:
        async with sem:
            bundle = await _run()
        dcf = bundle.dcf
        return dcf.upside_pct, dcf.implied_share_price, dcf.current_price, "ok"
    except asyncio.TimeoutError:
        logger.warning("valuate(%s) timed out after %.0fs", ticker, timeout)
        return None, None, None, "timeout"
    except ValueError as e:
        if "auditor blocked" in str(e).lower():
            logger.debug("valuate(%s) auditor blocked: %s", ticker, e)
            return None, None, None, "auditor_blocked"
        logger.warning("valuate(%s) value error: %s", ticker, e)
        return None, None, None, "valuation_error"
    except Exception as e:
        logger.warning("valuate(%s) failed: %s", ticker, e)
        return None, None, None, "valuation_error"


async def run_conviction_screener(
    top_n: int = 10,
    min_weight_pct: float = 1.0,
    min_buyers: int = 1,
    valuation_timeout: float = 90.0,
) -> ConvictionScreenerResponse:
    signal = await run_conviction_signal(
        min_weight_pct=min_weight_pct,
        min_buyers=min_buyers,
        top_n=top_n,
    )

    tickers: list[str | None] = [_resolve_ticker(s.issuer) for s in signal.signals]

    async def _unresolved() -> tuple[None, None, None, ValuationStatus]:
        return None, None, None, "ticker_unresolved"

    valuation_tasks = [
        _safe_valuate(t, timeout=valuation_timeout) if t else _unresolved()
        for t in tickers
    ]
    valuation_results = await asyncio.gather(*valuation_tasks)

    rows: list[ConvictionScreenRow] = []
    for rank, (sig, ticker, (upside, implied, current, status)) in enumerate(
        zip(signal.signals, tickers, valuation_results), start=1
    ):
        if ticker is None:
            status = "ticker_unresolved"

        rows.append(ConvictionScreenRow(
            rank=rank,
            issuer=sig.issuer,
            ticker=ticker,
            conviction_score=sig.conviction_score,
            buyer_count=sig.buyer_count,
            buyers=sig.buyers,
            max_weight_pct=sig.max_weight_pct,
            is_consensus=sig.is_consensus,
            upside_pct=upside,
            implied_price=implied,
            current_price=current,
            status=status,
        ))

    ok_count = sum(1 for r in rows if r.status == "ok")

    return ConvictionScreenerResponse(
        quarter=signal.quarter,
        dataset_label=signal.dataset_label,
        fundamental_funds_scanned=signal.fundamental_funds_scanned,
        rows=rows,
        valuation_ok_count=ok_count,
        valuation_failed_count=len(rows) - ok_count,
    )
