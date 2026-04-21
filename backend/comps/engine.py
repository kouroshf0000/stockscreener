from __future__ import annotations

import asyncio
import statistics
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from backend.comps.peer_map import peers_for
from backend.comps.peer_selector import select_peers
from backend.data_providers.models import Fundamentals
from backend.data_providers.yfinance_client import fetch_fundamentals
from backend.screener.metrics import ev_ebitda as calc_ev_ebitda
from backend.screener.metrics import pe_ratio as calc_pe


class PeerRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    symbol: str
    market_cap: Decimal | None
    pe_ratio: Decimal | None
    ev_ebitda: Decimal | None
    ev_revenue: Decimal | None = None
    ev_ebit: Decimal | None = None
    p_book: Decimal | None = None
    ev_fcf: Decimal | None = None
    peg: Decimal | None = None


class MultipleStat(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    target: Decimal | None
    peer_median: Decimal | None
    peer_weighted: Decimal | None
    premium_discount: Decimal | None
    implied_price: Decimal | None


class CompsResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    target: str
    peers: list[PeerRow]
    peer_selection_method: str = "unspecified"
    multiples: list[MultipleStat] = []
    weighted_pe: Decimal | None = None
    weighted_ev_ebitda: Decimal | None = None
    median_pe: Decimal | None = None
    median_ev_ebitda: Decimal | None = None
    implied_price_pe: Decimal | None = None
    implied_price_ev_ebitda: Decimal | None = None


def _weighted(multiples: list[tuple[Decimal, Decimal]]) -> Decimal | None:
    pairs = [(m, w) for m, w in multiples if m is not None and w and w > 0]
    if not pairs:
        return None
    total_w = sum(w for _, w in pairs)
    if total_w <= 0:
        return None
    return sum(m * w for m, w in pairs) / total_w


def _median(values: list[Decimal | None]) -> Decimal | None:
    nums = [float(v) for v in values if v is not None]
    if not nums:
        return None
    return Decimal(str(round(statistics.median(nums), 6)))


def _ev(f: Fundamentals) -> Decimal | None:
    if f.market_cap is None or not f.statements:
        return None
    s = f.statements[0]
    debt = s.total_debt or Decimal(0)
    lease = s.operating_lease_liability or Decimal(0)
    cash = s.cash_and_equivalents or Decimal(0)
    return f.market_cap + debt + lease - cash


def _ev_ratio(f: Fundamentals, field: str) -> Decimal | None:
    ev = _ev(f)
    if ev is None or not f.statements:
        return None
    v = getattr(f.statements[0], field, None)
    if v is None or v <= 0:
        return None
    return ev / v


def _p_book(f: Fundamentals) -> Decimal | None:
    if f.market_cap is None or not f.statements:
        return None
    equity = f.statements[0].total_equity
    if equity is None or equity <= 0:
        return None
    return f.market_cap / equity


def _peer_row(f: Fundamentals) -> PeerRow:
    return PeerRow(
        symbol=f.ticker,
        market_cap=f.market_cap,
        pe_ratio=calc_pe(f),
        ev_ebitda=calc_ev_ebitda(f),
        ev_revenue=_ev_ratio(f, "revenue"),
        ev_ebit=_ev_ratio(f, "operating_income"),
        p_book=_p_book(f),
        ev_fcf=_ev_ratio(f, "free_cash_flow"),
    )


def _implied_from_pe(target: Fundamentals, peer_pe: Decimal | None) -> Decimal | None:
    if peer_pe is None or not target.statements:
        return None
    ni = target.statements[0].net_income
    shares = target.statements[0].shares_outstanding
    if ni is None or ni <= 0 or shares is None or shares <= 0:
        return None
    eps = ni / shares
    return peer_pe * eps


def _implied_from_ev_multiple(
    target: Fundamentals, peer_mult: Decimal | None, field: str
) -> Decimal | None:
    if peer_mult is None or not target.statements:
        return None
    s = target.statements[0]
    v = getattr(s, field, None)
    if v is None or v <= 0 or s.shares_outstanding is None or s.shares_outstanding <= 0:
        return None
    implied_ev = peer_mult * v
    debt = s.total_debt or Decimal(0)
    lease = s.operating_lease_liability or Decimal(0)
    cash = s.cash_and_equivalents or Decimal(0)
    equity = implied_ev - debt - lease + cash
    if equity <= 0:
        return None
    return equity / s.shares_outstanding


def _pct_diff(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    if a is None or b is None or b == 0:
        return None
    return (a - b) / b


async def run_comps(ticker: str, universe: str = "SP500") -> CompsResult:
    target = await fetch_fundamentals(ticker)
    sym = target.ticker

    if sym in {*(peers_for(sym) and [sym])} or sym in __import__(
        "backend.comps.peer_map", fromlist=["PEER_OVERRIDES"]
    ).PEER_OVERRIDES:
        peer_syms = peers_for(sym)
        selection_method = "curated override"
    else:
        peer_syms = await select_peers(sym, universe_name=universe)
        selection_method = "auto: sector+industry+size-band"

    if not peer_syms:
        return CompsResult(
            target=sym, peers=[], peer_selection_method="none",
            multiples=[],
            weighted_pe=None, weighted_ev_ebitda=None,
            median_pe=None, median_ev_ebitda=None,
            implied_price_pe=None, implied_price_ev_ebitda=None,
        )

    fetched = await asyncio.gather(
        *(fetch_fundamentals(s) for s in peer_syms), return_exceptions=True
    )
    peers: list[PeerRow] = []
    for r in fetched:
        if isinstance(r, Exception):
            continue
        peers.append(_peer_row(r))

    target_row = _peer_row(target)

    def _stat(name: str, field: str, implied_fn) -> MultipleStat:
        peer_vals = [getattr(p, field) for p in peers]
        median = _median(peer_vals)
        weighted = _weighted(
            [(getattr(p, field), p.market_cap or Decimal(0)) for p in peers if getattr(p, field) is not None]
        )
        target_val = getattr(target_row, field)
        return MultipleStat(
            name=name,
            target=target_val,
            peer_median=median,
            peer_weighted=weighted,
            premium_discount=_pct_diff(target_val, median),
            implied_price=implied_fn(median),
        )

    multiples = [
        _stat("P/E", "pe_ratio", lambda m: _implied_from_pe(target, m)),
        _stat("EV/EBITDA", "ev_ebitda", lambda m: _implied_from_ev_multiple(target, m, "ebitda")),
        _stat("EV/EBIT", "ev_ebit", lambda m: _implied_from_ev_multiple(target, m, "operating_income")),
        _stat("EV/Revenue", "ev_revenue", lambda m: _implied_from_ev_multiple(target, m, "revenue")),
        _stat("EV/FCF", "ev_fcf", lambda m: _implied_from_ev_multiple(target, m, "free_cash_flow")),
        _stat("P/Book", "p_book", lambda m: None),
    ]

    weighted_pe = next((m.peer_weighted for m in multiples if m.name == "P/E"), None)
    weighted_ev = next((m.peer_weighted for m in multiples if m.name == "EV/EBITDA"), None)
    median_pe = next((m.peer_median for m in multiples if m.name == "P/E"), None)
    median_ev = next((m.peer_median for m in multiples if m.name == "EV/EBITDA"), None)
    implied_pe = next((m.implied_price for m in multiples if m.name == "P/E"), None)
    implied_ev = next((m.implied_price for m in multiples if m.name == "EV/EBITDA"), None)

    return CompsResult(
        target=sym,
        peers=peers,
        peer_selection_method=selection_method,
        multiples=multiples,
        weighted_pe=weighted_pe,
        weighted_ev_ebitda=weighted_ev,
        median_pe=median_pe,
        median_ev_ebitda=median_ev,
        implied_price_pe=implied_pe,
        implied_price_ev_ebitda=implied_ev,
    )
