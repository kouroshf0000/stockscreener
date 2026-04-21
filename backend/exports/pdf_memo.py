from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

from backend.comps.engine import CompsResult
from backend.nlp.models import RiskOutput
from backend.valuation.engine import ValuationBundle

NAVY = HexColor("#0A0E1A")
NAVY_2 = HexColor("#111827")
NAVY_3 = HexColor("#1E3A5F")
GOLD = HexColor("#C9A84C")
GREEN = HexColor("#22C55E")
RED = HexColor("#EF4444")
AMBER = HexColor("#F59E0B")
WHITE = HexColor("#F9FAFB")
MUTED = HexColor("#94A3B8")
LIGHT = HexColor("#CBD5E1")


def _money(value: object) -> str:
    try:
        return f"${float(value):,.2f}"
    except Exception:
        return "-"


def _pct(value: object) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except Exception:
        return "-"


def _draw_header(c: canvas.Canvas, page_no: int) -> None:
    width, height = LETTER
    c.setFillColor(NAVY)
    c.rect(0, height - 0.55 * inch, width, 0.55 * inch, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.55 * inch, height - 0.35 * inch, "AlphaArchitect Research | CONFIDENTIAL")
    c.drawRightString(width - 0.55 * inch, height - 0.35 * inch, f"Page {page_no}")


def _draw_footer(c: canvas.Canvas) -> None:
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 8)
    c.drawString(
        0.55 * inch,
        0.35 * inch,
        "For professional use only. Not investment advice. Data sources: SEC EDGAR, yfinance, FRED.",
    )


def _section_title(c: canvas.Canvas, y: float, title: str) -> float:
    c.setFillColor(GOLD)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(0.65 * inch, y, title)
    c.setStrokeColor(NAVY_3)
    c.line(0.65 * inch, y - 6, 7.95 * inch, y - 6)
    return y - 18


def _line(c: canvas.Canvas, y: float, label: str, value: str, *, tone=WHITE) -> float:
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 9)
    c.drawString(0.75 * inch, y, label)
    c.setFillColor(tone)
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(3.85 * inch, y, value)
    return y - 14


def _wrap_text(c: canvas.Canvas, text: str, x: float, y: float, width: float, leading: float = 12) -> float:
    words = text.split()
    line = ""
    c.setFont("Helvetica", 9)
    c.setFillColor(LIGHT)
    for word in words:
        trial = f"{line} {word}".strip()
        if c.stringWidth(trial, "Helvetica", 9) > width and line:
            c.drawString(x, y, line)
            y -= leading
            line = word
        else:
            line = trial
    if line:
        c.drawString(x, y, line)
        y -= leading
    return y


def _scenario_rows(val: ValuationBundle) -> list[tuple[str, str, str, str]]:
    if val.scenarios is None:
        return []
    return [
        ("Bull", _money(val.scenarios.bull.implied_price), _pct(val.scenarios.bull.upside_pct), val.scenarios.bull.description),
        ("Base", _money(val.scenarios.base.implied_price), _pct(val.scenarios.base.upside_pct), val.scenarios.base.description),
        ("Bear", _money(val.scenarios.bear.implied_price), _pct(val.scenarios.bear.upside_pct), val.scenarios.bear.description),
    ]


def _football_chart(c: canvas.Canvas, y: float, val: ValuationBundle) -> float:
    rows = val.football_field.rows if val.football_field else []
    if not rows:
        c.setFillColor(MUTED)
        c.drawString(0.75 * inch, y, "No football-field inputs available.")
        return y - 18

    nums = [float(row.low) for row in rows] + [float(row.high) for row in rows]
    if val.football_field.current_price is not None:
        nums.append(float(val.football_field.current_price))
    min_v = min(nums)
    max_v = max(nums)
    span = max(max_v - min_v, 1.0)
    left = 1.9 * inch
    right = 7.6 * inch
    width = right - left
    current = float(val.football_field.current_price) if val.football_field and val.football_field.current_price is not None else None

    for idx, row in enumerate(rows):
        row_y = y - idx * 22
        c.setFillColor(LIGHT)
        c.setFont("Helvetica", 8)
        c.drawString(0.75 * inch, row_y + 3, row.label)
        low = float(row.low)
        high = float(row.high)
        x1 = left + ((low - min_v) / span) * width
        x2 = left + ((high - min_v) / span) * width
        c.setFillColor(NAVY_3)
        c.rect(x1, row_y - 2, max(x2 - x1, 1.5), 8, fill=1, stroke=0)
        c.setFillColor(MUTED)
        c.drawString(right + 8, row_y + 3, _money(row.midpoint))
        if current is not None:
            cx = left + ((current - min_v) / span) * width
            c.setStrokeColor(RED)
            c.line(cx, row_y - 6, cx, row_y + 10)
    return y - len(rows) * 22 - 8


def build_pdf(
    path: str | Path,
    val: ValuationBundle,
    comps: CompsResult | None = None,
    risk: RiskOutput | None = None,
    scout_context: dict[str, object] | None = None,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=LETTER)
    width, height = LETTER

    rating = val.blended_target.rating if val.blended_target and val.blended_target.rating else "NEUTRAL"
    rating_color = GREEN if rating == "OUTPERFORM" else RED if rating == "UNDERPERFORM" else AMBER
    company_name = scout_context.get("company_name") if isinstance(scout_context, dict) else None
    company_name = company_name if isinstance(company_name, str) and company_name else val.dcf.ticker

    # Page 1: Cover
    _draw_header(c, 1)
    _draw_footer(c)
    c.setFillColor(NAVY)
    c.rect(0.55 * inch, height - 2.2 * inch, width - 1.1 * inch, 1.2 * inch, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 24)
    c.drawString(0.8 * inch, height - 1.45 * inch, str(company_name))
    c.setFont("Helvetica", 10)
    c.drawString(0.8 * inch, height - 1.75 * inch, "UPDATE")
    c.drawRightString(width - 0.8 * inch, height - 1.2 * inch, val.dcf.as_of.isoformat())

    c.setFillColor(rating_color)
    c.rect(0.8 * inch, height - 2.75 * inch, 1.65 * inch, 0.38 * inch, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(1.625 * inch, height - 2.5 * inch, rating)

    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(0.8 * inch, height - 3.35 * inch, f"Price Target: {_money(val.blended_target.price if val.blended_target else val.dcf.implied_share_price)}")
    c.setFont("Helvetica", 11)
    c.drawString(
        0.8 * inch,
        height - 3.7 * inch,
        f"Current Price {_money(val.dcf.current_price)} | Upside {_pct(val.blended_target.upside_pct if val.blended_target else val.dcf.upside_pct)}",
    )

    bullets = []
    if val.news and val.news.summary:
        bullets.append(val.news.summary)
    if val.blended_target and val.blended_target.regime:
        bullets.append(f"Blended target uses a {val.blended_target.regime} weighting regime with {val.blended_target.confidence} confidence.")
    bullets.append(
        f"DCF implies {_money(val.dcf.implied_share_price)} per share on WACC {_pct(val.dcf.wacc.wacc)} and terminal growth {_pct(val.dcf.assumptions.terminal_growth)}."
    )
    y = height - 4.3 * inch
    c.setStrokeColor(NAVY_3)
    c.line(0.8 * inch, y + 0.15 * inch, width - 0.8 * inch, y + 0.15 * inch)
    c.setFont("Helvetica", 10)
    for bullet in bullets[:3]:
        c.setFillColor(GOLD)
        c.drawString(0.9 * inch, y, "•")
        y = _wrap_text(c, bullet, 1.1 * inch, y, width - 2.0 * inch)
        y -= 4

    c.setFillColor(MUTED)
    c.setFont("Helvetica", 9)
    c.drawString(0.8 * inch, 1.35 * inch, "Analyst: AlphaArchitect Research Team")
    disclaimer = (
        "This research note is generated from public filings and market data to support professional analysis. "
        "It is not investment advice and should not be treated as a recommendation to buy or sell securities."
    )
    _wrap_text(c, disclaimer, 0.8 * inch, 1.0 * inch, width - 1.6 * inch, leading=10)
    c.showPage()

    # Page 2: Valuation
    _draw_header(c, 2)
    _draw_footer(c)
    y = height - 0.95 * inch
    y = _section_title(c, y, "VALUATION")
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75 * inch, y, "Methodology")
    c.drawString(3.25 * inch, y, "Weight")
    c.drawString(4.15 * inch, y, "Implied")
    c.drawString(5.35 * inch, y, "Contribution")
    y -= 14
    for row in (val.blended_target.methodology_weights if val.blended_target else []):
        c.setFillColor(LIGHT)
        c.setFont("Helvetica", 9)
        c.drawString(0.75 * inch, y, row.name)
        c.drawString(3.25 * inch, y, _pct(row.weight))
        c.drawString(4.15 * inch, y, _money(row.implied_price))
        c.drawString(5.35 * inch, y, _money(row.weighted_contribution))
        y -= 13
    y -= 8
    y = _section_title(c, y, "FOOTBALL FIELD")
    y = _football_chart(c, y, val)
    y -= 6
    y = _section_title(c, y, "SCENARIOS")
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75 * inch, y, "Case")
    c.drawString(1.6 * inch, y, "Price")
    c.drawString(2.5 * inch, y, "Upside")
    c.drawString(3.3 * inch, y, "Description")
    y -= 14
    for case, price, upside, desc in _scenario_rows(val):
        c.setFillColor(LIGHT)
        c.setFont("Helvetica", 9)
        c.drawString(0.75 * inch, y, case)
        c.drawString(1.6 * inch, y, price)
        c.drawString(2.5 * inch, y, upside)
        y = _wrap_text(c, desc, 3.3 * inch, y, 4.0 * inch, leading=11)
    c.showPage()

    # Page 3: Financial summary
    _draw_header(c, 3)
    _draw_footer(c)
    y = height - 0.95 * inch
    y = _section_title(c, y, "FINANCIALS")
    headers = ["Year", "Revenue", "EBIT", "NOPAT", "FCFF", "PV FCFF"]
    x_positions = [0.75, 1.55, 2.7, 3.85, 4.95, 6.0]
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 9)
    for header, x in zip(headers, x_positions):
        c.drawString(x * inch, y, header)
    y -= 14
    c.setFont("Helvetica", 8)
    c.setFillColor(LIGHT)
    for projection in val.dcf.projections:
        values = [
            f"Y{projection.year}",
            _money(projection.revenue),
            _money(projection.ebit),
            _money(projection.nopat),
            _money(projection.fcff),
            _money(projection.pv_fcff),
        ]
        for value, x in zip(values, x_positions):
            c.drawString(x * inch, y, value)
        y -= 12
    y -= 10
    y = _section_title(c, y, "WACC BREAKDOWN")
    y = _line(c, y, "Cost of Equity", _pct(val.dcf.wacc.cost_of_equity))
    y = _line(c, y, "Cost of Debt (After Tax)", _pct(val.dcf.wacc.cost_of_debt_after_tax))
    y = _line(c, y, "Weight of Equity", _pct(val.dcf.wacc.weight_equity))
    y = _line(c, y, "Weight of Debt", _pct(val.dcf.wacc.weight_debt))
    y = _line(c, y, "WACC", _pct(val.dcf.wacc.wacc), tone=GOLD)
    y -= 8
    y = _section_title(c, y, "KEY ASSUMPTIONS")
    for key, value in list(val.provenance.items())[:8]:
        y = _line(c, y, key, value)
    c.showPage()

    # Page 4: Risks
    _draw_header(c, 4)
    _draw_footer(c)
    y = height - 0.95 * inch
    y = _section_title(c, y, "KEY RISKS")
    if risk is not None:
        y = _line(c, y, "Legal", str(risk.assessment.legal_risk))
        y = _line(c, y, "Regulatory", str(risk.assessment.regulatory_risk))
        y = _line(c, y, "Macro", str(risk.assessment.macro_risk))
        y = _line(c, y, "Competitive", str(risk.assessment.competitive_risk))
        y = _line(c, y, "Discount Rate Adjustment", _pct(risk.discount_rate_adjustment), tone=AMBER)
        y -= 8
        y = _section_title(c, y, "TOP RISKS")
        bullets = risk.assessment.top_risks or [risk.assessment.summary]
        c.setFillColor(LIGHT)
        c.setFont("Helvetica", 9)
        for bullet in bullets[:6]:
            c.drawString(0.8 * inch, y, "•")
            y = _wrap_text(c, bullet, 1.0 * inch, y, width - 1.8 * inch, leading=11)
            y -= 3
        if risk.source == "haiku" and risk.filing_accession:
            y -= 6
            c.setFillColor(MUTED)
            c.drawString(
                0.75 * inch,
                y,
                f"Extracted from 10-K filing {risk.filing_accession} ({risk.filing_form}, {risk.filing_date}).",
            )
    else:
        c.setFillColor(MUTED)
        c.drawString(0.75 * inch, y, "Risk assessment unavailable.")

    c.save()
    return path
