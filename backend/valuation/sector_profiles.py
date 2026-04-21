"""
Sector-adaptive parameter profiles for the DCF model.

Each profile encodes the structural economics of a sector so the model
avoids universal hardcodes. Parameters are expressed as (low, mid, high)
bands — the model uses the mid as a prior and the data-derived value is
pulled toward the band if it falls outside, rather than clipped hard.

Sector names match yfinance's `.sector` field.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class SectorProfile:
    # EBIT margin: sustainable operating margin range for mature companies
    margin_floor: Decimal       # minimum realistic terminal margin
    margin_ceiling: Decimal     # maximum realistic terminal margin
    margin_prior: Decimal       # prior if data is sparse

    # Reinvestment: net capex + NWC as % of NOPAT
    reinv_prior: Decimal        # sector baseline when data is unavailable
    reinv_floor: Decimal
    reinv_ceiling: Decimal

    # Terminal revenue growth (used to bound fade endpoint)
    terminal_growth_prior: Decimal  # sector-specific steady-state growth

    # Effective tax rate floor (some sectors have structural tax advantages)
    tax_floor: Decimal

    # Beta: typical range — used to sanity-check yfinance raw beta
    beta_floor: Decimal
    beta_ceiling: Decimal

    # EV/EBITDA: typical peer trading range (used as prior for exit multiple)
    ev_ebitda_typical: Decimal | None


_D = Decimal

PROFILES: dict[str, SectorProfile] = {
    "Technology": SectorProfile(
        margin_floor=_D("0.12"),  margin_ceiling=_D("0.50"), margin_prior=_D("0.25"),
        reinv_prior=_D("0.20"),   reinv_floor=_D("0.05"),    reinv_ceiling=_D("0.55"),
        terminal_growth_prior=_D("0.035"),
        tax_floor=_D("0.12"),
        beta_floor=_D("0.70"),    beta_ceiling=_D("1.80"),
        ev_ebitda_typical=_D("22"),
    ),
    "Communication Services": SectorProfile(
        margin_floor=_D("0.15"),  margin_ceiling=_D("0.45"), margin_prior=_D("0.28"),
        reinv_prior=_D("0.25"),   reinv_floor=_D("0.08"),    reinv_ceiling=_D("0.55"),
        terminal_growth_prior=_D("0.030"),
        tax_floor=_D("0.14"),
        beta_floor=_D("0.70"),    beta_ceiling=_D("1.60"),
        ev_ebitda_typical=_D("18"),
    ),
    "Healthcare": SectorProfile(
        margin_floor=_D("0.08"),  margin_ceiling=_D("0.40"), margin_prior=_D("0.20"),
        reinv_prior=_D("0.35"),   reinv_floor=_D("0.15"),    reinv_ceiling=_D("0.65"),
        terminal_growth_prior=_D("0.030"),
        tax_floor=_D("0.14"),
        beta_floor=_D("0.50"),    beta_ceiling=_D("1.50"),
        ev_ebitda_typical=_D("16"),
    ),
    "Consumer Discretionary": SectorProfile(
        margin_floor=_D("0.05"),  margin_ceiling=_D("0.25"), margin_prior=_D("0.12"),
        reinv_prior=_D("0.40"),   reinv_floor=_D("0.20"),    reinv_ceiling=_D("0.70"),
        terminal_growth_prior=_D("0.025"),
        tax_floor=_D("0.18"),
        beta_floor=_D("0.70"),    beta_ceiling=_D("1.80"),
        ev_ebitda_typical=_D("12"),
    ),
    "Consumer Staples": SectorProfile(
        margin_floor=_D("0.08"),  margin_ceiling=_D("0.22"), margin_prior=_D("0.14"),
        reinv_prior=_D("0.30"),   reinv_floor=_D("0.15"),    reinv_ceiling=_D("0.55"),
        terminal_growth_prior=_D("0.020"),
        tax_floor=_D("0.18"),
        beta_floor=_D("0.40"),    beta_ceiling=_D("1.20"),
        ev_ebitda_typical=_D("15"),
    ),
    "Financials": SectorProfile(
        margin_floor=_D("0.15"),  margin_ceiling=_D("0.40"), margin_prior=_D("0.25"),
        reinv_prior=_D("0.30"),   reinv_floor=_D("0.10"),    reinv_ceiling=_D("0.60"),
        terminal_growth_prior=_D("0.025"),
        tax_floor=_D("0.18"),
        beta_floor=_D("0.60"),    beta_ceiling=_D("1.60"),
        ev_ebitda_typical=_D("12"),
    ),
    "Industrials": SectorProfile(
        margin_floor=_D("0.06"),  margin_ceiling=_D("0.22"), margin_prior=_D("0.13"),
        reinv_prior=_D("0.45"),   reinv_floor=_D("0.25"),    reinv_ceiling=_D("0.70"),
        terminal_growth_prior=_D("0.020"),
        tax_floor=_D("0.18"),
        beta_floor=_D("0.70"),    beta_ceiling=_D("1.50"),
        ev_ebitda_typical=_D("13"),
    ),
    "Energy": SectorProfile(
        margin_floor=_D("0.05"),  margin_ceiling=_D("0.25"), margin_prior=_D("0.12"),
        reinv_prior=_D("0.55"),   reinv_floor=_D("0.30"),    reinv_ceiling=_D("0.80"),
        terminal_growth_prior=_D("0.015"),
        tax_floor=_D("0.18"),
        beta_floor=_D("0.80"),    beta_ceiling=_D("1.80"),
        ev_ebitda_typical=_D("7"),
    ),
    "Materials": SectorProfile(
        margin_floor=_D("0.05"),  margin_ceiling=_D("0.22"), margin_prior=_D("0.12"),
        reinv_prior=_D("0.50"),   reinv_floor=_D("0.25"),    reinv_ceiling=_D("0.75"),
        terminal_growth_prior=_D("0.020"),
        tax_floor=_D("0.18"),
        beta_floor=_D("0.70"),    beta_ceiling=_D("1.60"),
        ev_ebitda_typical=_D("9"),
    ),
    "Real Estate": SectorProfile(
        margin_floor=_D("0.20"),  margin_ceiling=_D("0.55"), margin_prior=_D("0.35"),
        reinv_prior=_D("0.50"),   reinv_floor=_D("0.30"),    reinv_ceiling=_D("0.70"),
        terminal_growth_prior=_D("0.020"),
        tax_floor=_D("0.10"),
        beta_floor=_D("0.50"),    beta_ceiling=_D("1.40"),
        ev_ebitda_typical=_D("18"),
    ),
    "Utilities": SectorProfile(
        margin_floor=_D("0.10"),  margin_ceiling=_D("0.28"), margin_prior=_D("0.18"),
        reinv_prior=_D("0.60"),   reinv_floor=_D("0.40"),    reinv_ceiling=_D("0.80"),
        terminal_growth_prior=_D("0.015"),
        tax_floor=_D("0.18"),
        beta_floor=_D("0.30"),    beta_ceiling=_D("0.90"),
        ev_ebitda_typical=_D("10"),
    ),
}

# Fallback when sector is unknown
DEFAULT_PROFILE = SectorProfile(
    margin_floor=_D("0.08"),  margin_ceiling=_D("0.35"), margin_prior=_D("0.15"),
    reinv_prior=_D("0.35"),   reinv_floor=_D("0.05"),    reinv_ceiling=_D("0.70"),
    terminal_growth_prior=_D("0.025"),
    tax_floor=_D("0.18"),
    beta_floor=_D("0.50"),    beta_ceiling=_D("2.00"),
    ev_ebitda_typical=None,
)


# yfinance sector labels don't always match Damodaran/GICS labels
_SECTOR_ALIASES: dict[str, str] = {
    # yfinance → canonical
    "Financial Services": "Financials",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Basic Materials": "Materials",
    "Communication Services": "Communication Services",
}


def get_profile(sector: str | None) -> SectorProfile:
    if not sector:
        return DEFAULT_PROFILE
    canonical = _SECTOR_ALIASES.get(sector, sector)
    return PROFILES.get(canonical, DEFAULT_PROFILE)
