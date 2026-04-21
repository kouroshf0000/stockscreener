"""
Input data quality auditor for the valuation pipeline.

Checks run before any model computation. Findings split into:
- BLOCKING (ok=False): model cannot run reliably without this data
- WARNING (ok=True, detail starts with "WARN"): model can run but results may be impaired
- INFO (ok=True): informational, no impact on reliability

All checks use only the fundamentals object — no external calls.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from backend.data_providers.models import Fundamentals
from backend.valuation.models import AuditFinding


def _find(rule: str, ok: bool, detail: str) -> AuditFinding:
    return AuditFinding(rule=rule, ok=ok, detail=detail)


def _warn(rule: str, detail: str) -> AuditFinding:
    return AuditFinding(rule=rule, ok=True, detail=f"WARN: {detail}")


def _info(rule: str, detail: str) -> AuditFinding:
    return AuditFinding(rule=rule, ok=True, detail=detail)


def audit(f: Fundamentals) -> list[AuditFinding]:  # noqa: C901
    findings: list[AuditFinding] = []

    # ── 1. Statement coverage ───────────────────────────────────────────────
    if not f.statements:
        findings.append(_find("statements_present", False, "no financial statements available"))
        return findings  # cannot proceed

    n_stmts = len(f.statements)
    if n_stmts < 2:
        findings.append(_find("statements_coverage", False,
                               f"only {n_stmts} year(s) of data; need ≥2 for CAGR and margin derivation"))
        return findings
    elif n_stmts < 4:
        findings.append(_warn("statements_coverage",
                               f"only {n_stmts} year(s) of statements; 4+ preferred for stable averages"))
    else:
        findings.append(_info("statements_coverage", f"{n_stmts} years of statements available"))

    s = f.statements[0]

    # ── 2. Data staleness ───────────────────────────────────────────────────
    months_old = (date.today() - s.period_end).days / 30
    if months_old > 18:
        findings.append(_warn("data_staleness",
                               f"most recent statement is {months_old:.0f} months old; results may lag materially"))
    else:
        findings.append(_info("data_staleness", f"latest statement: {s.period_end} ({months_old:.0f}mo ago)"))

    # ── 3. Market cap ───────────────────────────────────────────────────────
    if f.market_cap is None or f.market_cap <= 0:
        findings.append(_find("market_cap", False, "market_cap missing or zero — cannot compute WACC weights or implied upside"))
    else:
        findings.append(_info("market_cap", f"${f.market_cap / Decimal('1e9'):.1f}B"))

    # ── 4. Shares outstanding — cross-validate against market_cap / price ──
    if s.shares_outstanding is None or s.shares_outstanding <= 0:
        findings.append(_find("shares_outstanding", False, "shares outstanding missing — cannot compute per-share implied price"))
    else:
        findings.append(_info("shares_outstanding", f"{s.shares_outstanding / Decimal('1e9'):.2f}B shares"))
        if f.market_cap and f.price and f.price > 0:
            implied_shares = f.market_cap / f.price
            delta = abs(s.shares_outstanding - implied_shares) / implied_shares
            if delta > Decimal("0.25"):
                findings.append(_warn(
                    "shares_consistency",
                    f"balance-sheet shares ({s.shares_outstanding / Decimal('1e6'):.0f}M) vs "
                    f"market_cap/price implied ({implied_shares / Decimal('1e6'):.0f}M) diverge {delta:.0%}; "
                    f"diluted share count may include unexercised options/warrants",
                ))

    # ── 5. Revenue ──────────────────────────────────────────────────────────
    if s.revenue is None or s.revenue <= 0:
        findings.append(_find("revenue", False, "latest revenue missing or zero — DCF anchor unavailable"))
    else:
        findings.append(_info("revenue", f"${s.revenue / Decimal('1e9'):.1f}B"))
        # Revenue growth YoY sanity
        if len(f.statements) >= 2:
            prev = f.statements[1].revenue
            if prev and prev > 0:
                yoy = (s.revenue - prev) / prev
                if abs(yoy) > Decimal("1.0"):
                    findings.append(_warn("revenue_growth_outlier",
                                           f"YoY revenue change of {yoy:.0%} is extreme; verify no one-off reclassification"))

    # ── 6. Operating income (EBIT) ──────────────────────────────────────────
    if s.operating_income is None:
        findings.append(_warn("operating_income", "EBIT missing from latest statement; margin path will use sector prior"))
    else:
        if s.revenue and s.revenue > 0:
            margin = s.operating_income / s.revenue
            if margin < Decimal("-0.50"):
                findings.append(_warn("operating_margin_extreme",
                                       f"EBIT margin of {margin:.0%} is deeply negative; DCF will floor to sector minimum"))
            elif margin > Decimal("0.80"):
                findings.append(_warn("operating_margin_extreme",
                                       f"EBIT margin of {margin:.0%} is unusually high; verify no non-recurring gain"))

    # ── 7. Capex & D&A ─────────────────────────────────────────────────────
    if s.capex is None:
        findings.append(_warn("capex", "capex missing; reinvestment rate will rely on sector prior only"))
    if s.depreciation_and_amortization is None:
        findings.append(_warn("da", "D&A missing; net capex = gross capex (reinvestment may be overstated)"))

    # ── 8. FCF consistency check ────────────────────────────────────────────
    if s.free_cash_flow is not None and s.operating_cash_flow is not None and s.capex is not None:
        reconstructed = s.operating_cash_flow + s.capex  # capex is negative
        if s.free_cash_flow != 0:
            delta = abs(reconstructed - s.free_cash_flow) / abs(s.free_cash_flow)
            if delta > Decimal("0.05"):
                findings.append(_warn(
                    "fcf_consistency",
                    f"reported FCF (${s.free_cash_flow / Decimal('1e9'):.1f}B) differs from "
                    f"OCF+capex (${reconstructed / Decimal('1e9'):.1f}B) by {delta:.0%}; "
                    f"yfinance may use a different FCF definition",
                ))

    # ── 9. Debt ─────────────────────────────────────────────────────────────
    if s.total_debt is None:
        findings.append(_warn("debt", "total_debt missing; net debt assumed zero in equity bridge"))
    else:
        findings.append(_info("debt", f"${s.total_debt / Decimal('1e9'):.1f}B total debt"))

    # ── 10. Beta ────────────────────────────────────────────────────────────
    if f.beta is None:
        findings.append(_warn("beta", "beta not available from yfinance; will be computed from 2Y weekly returns"))
    elif f.beta > Decimal("2.5") or f.beta < Decimal("0.2"):
        findings.append(_warn("beta", f"raw beta of {f.beta} is outside normal range — sector clamp will be applied"))

    return findings


def auditor_passes(findings: list[AuditFinding]) -> bool:
    """Block valuation if any BLOCKING finding (ok=False) exists."""
    return all(f.ok for f in findings)
