"""
Quick DCF assumption audit for a list of tickers.
Usage: uv run python scripts/dcf_audit.py AMZN META GOOGL ASML DASH CRS
"""
from __future__ import annotations

import asyncio
import sys

from dotenv import load_dotenv
load_dotenv()

from backend.filings.conviction_screener import _safe_valuate
from backend.valuation.engine import valuate


async def audit_ticker(ticker: str) -> None:
    print(f"\n{'='*70}")
    print(f"  {ticker}")
    print(f"{'='*70}")
    try:
        bundle = await valuate(ticker, include_monte_carlo=False, include_overlays=False)
        dcf = bundle.dcf
        a = dcf.assumptions
        w = dcf.wacc

        print(f"  Sector:           {getattr(bundle.dcf, 'ticker', '?')} — check yfinance .sector in fundamentals")
        print(f"  Current price:    ${float(dcf.current_price or 0):,.2f}")
        print(f"  Implied price:    ${float(dcf.implied_share_price):,.2f}")
        print(f"  Upside:           {float(dcf.upside_pct or 0)*100:+.1f}%")
        print()
        print(f"  WACC:             {float(w.wacc)*100:.2f}%")
        print(f"    Cost of equity: {float(w.cost_of_equity)*100:.2f}%")
        print(f"    Cost of debt:   {float(w.cost_of_debt_after_tax)*100:.2f}% (after-tax)")
        print(f"    Weight equity:  {float(w.weight_equity)*100:.1f}%")
        print(f"    Weight debt:    {float(w.weight_debt)*100:.1f}%")
        print()
        print(f"  Terminal growth:  {float(a.terminal_growth)*100:.2f}%")
        print(f"  EBIT margin Y1:   {float(a.ebit_margin_path[0] if a.ebit_margin_path else a.ebit_margin)*100:.1f}%")
        print(f"  EBIT margin Y10:  {float(a.ebit_margin_path[-1] if a.ebit_margin_path else a.ebit_margin)*100:.1f}%")
        print(f"  Reinvestment:     {float(a.reinvestment_rate)*100:.1f}%")
        print(f"  Tax rate:         {float(a.tax_rate)*100:.1f}%")
        print(f"  Exit EV/EBITDA:   {float(a.exit_multiple_ev_ebitda)}x" if a.exit_multiple_ev_ebitda else "  Exit EV/EBITDA:   not set")
        print()
        growth = a.revenue_growth
        print(f"  Revenue growth:   Y1={float(growth[0])*100:.1f}% Y2={float(growth[1])*100:.1f}% "
              f"Y3={float(growth[2])*100:.1f}% Y5={float(growth[4])*100:.1f}% "
              f"Y10={float(growth[9])*100:.1f}%")
        print()
        print(f"  PV explicit:      ${float(dcf.pv_explicit)/1e9:.1f}B")
        print(f"  PV terminal:      ${float(dcf.pv_terminal)/1e9:.1f}B")
        print(f"  Enterprise value: ${float(dcf.enterprise_value)/1e9:.1f}B")
        print(f"  Net debt:         ${float(dcf.net_debt)/1e9:.1f}B")
        print(f"  Equity value:     ${float(dcf.equity_value)/1e9:.1f}B")
        if dcf.red_flags:
            print()
            print("  Red flags:")
            for f_ in dcf.red_flags:
                print(f"    ⚠  {f_}")
        if bundle.provenance:
            print()
            print("  Provenance:")
            for k, v in bundle.provenance.items():
                print(f"    {k}: {v}")
    except Exception as e:
        print(f"  ERROR: {e}")


async def main(tickers: list[str]) -> None:
    for ticker in tickers:
        await audit_ticker(ticker)
    print()


if __name__ == "__main__":
    tickers = sys.argv[1:] if len(sys.argv) > 1 else ["AMZN", "GOOGL", "ASML", "DASH", "CRS"]
    asyncio.run(main(tickers))
