from __future__ import annotations

from decimal import Decimal

from backend.comps.engine import CompsResult
from backend.hunter.models import GateCheck
from backend.valuation.engine import ValuationBundle

MIN_UPSIDE = Decimal("0.20")
MAX_COMPS_DIVERGENCE = Decimal("0.25")
MIN_MARKET_CAP = Decimal("2_000_000_000")


def run_gate(
    val: ValuationBundle,
    comps: CompsResult | None,
    market_cap: Decimal | None,
    legal_risk: int | None,
) -> tuple[bool, list[GateCheck]]:
    checks: list[GateCheck] = []

    upside = val.dcf.upside_pct
    if upside is None:
        checks.append(GateCheck(rule="upside", result="fail", detail="no current price"))
    elif upside < MIN_UPSIDE:
        checks.append(
            GateCheck(
                rule="upside",
                result="fail",
                detail=f"{float(upside) * 100:.1f}% < {float(MIN_UPSIDE) * 100:.0f}%",
            )
        )
    else:
        checks.append(
            GateCheck(
                rule="upside",
                result="pass",
                detail=f"{float(upside) * 100:.1f}% DCF upside",
            )
        )

    dcf_px = val.dcf.implied_share_price
    comps_candidates = []
    if comps:
        if comps.implied_price_pe is not None:
            comps_candidates.append(comps.implied_price_pe)
        if comps.implied_price_ev_ebitda is not None:
            comps_candidates.append(comps.implied_price_ev_ebitda)
    if comps_candidates and dcf_px > 0:
        divergences = [abs(c - dcf_px) / dcf_px for c in comps_candidates]
        min_div = min(divergences)
        if min_div <= MAX_COMPS_DIVERGENCE:
            checks.append(
                GateCheck(
                    rule="comps_agreement",
                    result="pass",
                    detail=f"closest comp within {float(min_div) * 100:.1f}%",
                )
            )
        else:
            checks.append(
                GateCheck(
                    rule="comps_agreement",
                    result="fail",
                    detail=f"DCF diverges {float(min_div) * 100:.1f}% from best comp",
                )
            )
    else:
        checks.append(
            GateCheck(
                rule="comps_agreement",
                result="fail",
                detail="no comps available for cross-check",
            )
        )

    if val.auditor_ok:
        checks.append(GateCheck(rule="auditor", result="pass", detail="data reconciled"))
    else:
        checks.append(GateCheck(rule="auditor", result="fail", detail="auditor findings"))

    if legal_risk is not None and legal_risk >= 3:
        checks.append(
            GateCheck(rule="legal_risk", result="fail", detail=f"legal_risk={legal_risk}")
        )
    else:
        checks.append(GateCheck(rule="legal_risk", result="pass", detail="acceptable"))

    if market_cap is None or market_cap < MIN_MARKET_CAP:
        checks.append(
            GateCheck(rule="liquidity", result="fail", detail=f"market_cap={market_cap}")
        )
    else:
        checks.append(
            GateCheck(rule="liquidity", result="pass", detail=f"market_cap={market_cap}")
        )

    passed = all(c.result == "pass" for c in checks)
    return passed, checks
