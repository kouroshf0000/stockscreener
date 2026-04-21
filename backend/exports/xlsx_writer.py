from __future__ import annotations

from pathlib import Path

import xlsxwriter

from backend.comps.engine import CompsResult
from backend.nlp.models import RiskOutput
from backend.valuation.engine import ValuationBundle

SHEET_PASSWORD = "alpha"


def _formats(book: xlsxwriter.Workbook) -> dict[str, xlsxwriter.format.Format]:
    return {
        "title": book.add_format({"bold": True, "font_size": 18, "font_color": "#F9FAFB", "bg_color": "#0A0E1A"}),
        "subtitle": book.add_format({"font_size": 10, "font_color": "#94A3B8", "bg_color": "#0A0E1A"}),
        "header": book.add_format({"bold": True, "font_color": "#F9FAFB", "bg_color": "#1E3A5F", "border": 1}),
        "subheader": book.add_format({"bold": True, "font_color": "#F9FAFB", "bg_color": "#111827", "border": 1}),
        "body": book.add_format({"font_color": "#E5E7EB", "bg_color": "#111827", "border": 1}),
        "money": book.add_format({"font_color": "#E5E7EB", "bg_color": "#111827", "border": 1, "num_format": "$#,##0.00"}),
        "pct": book.add_format({"font_color": "#E5E7EB", "bg_color": "#111827", "border": 1, "num_format": "0.00%"}),
        "gold": book.add_format({"bold": True, "font_color": "#0A0E1A", "bg_color": "#C9A84C", "border": 1}),
        "warning": book.add_format({"font_color": "#FCD34D", "bg_color": "#2A2412", "border": 1}),
        "input": book.add_format({"font_color": "#E5E7EB", "bg_color": "#172033", "border": 1, "locked": False}),
    }


def _sheet_header(ws: xlsxwriter.worksheet.Worksheet, title: str, subtitle: str, fmts: dict[str, xlsxwriter.format.Format]) -> int:
    ws.merge_range("A1:H1", title, fmts["title"])
    ws.merge_range("A2:H2", subtitle, fmts["subtitle"])
    return 3


def _money(value: object) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _pct(value: object) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _cover(ws: xlsxwriter.worksheet.Worksheet, val: ValuationBundle, fmts) -> None:
    row = _sheet_header(ws, f"{val.dcf.ticker} Research Packet", "AlphaArchitect Research", fmts)
    entries = [
        ("Date", val.dcf.as_of.isoformat()),
        ("Rating", val.blended_target.rating if val.blended_target else "NEUTRAL"),
        ("Price Target", _money(val.blended_target.price if val.blended_target else val.dcf.implied_share_price)),
        ("Current Price", _money(val.dcf.current_price)),
        ("Upside", _pct(val.blended_target.upside_pct if val.blended_target else val.dcf.upside_pct)),
        ("Confidence", val.blended_target.confidence.upper() if val.blended_target else "MEDIUM"),
    ]
    for label, value in entries:
        ws.write(row, 0, label, fmts["subheader"])
        if isinstance(value, float):
            fmt = fmts["pct"] if "Upside" in label else fmts["money"]
            ws.write_number(row, 1, value, fmt)
        else:
            ws.write(row, 1, value, fmts["body"])
        row += 1


def _executive_summary(ws: xlsxwriter.worksheet.Worksheet, val: ValuationBundle, risk: RiskOutput | None, fmts) -> None:
    row = _sheet_header(ws, "Executive Summary", "Blend, quality flags, and thesis bullets", fmts)
    ws.write_row(row, 0, ["Methodology", "Weight", "Implied", "Contribution"], fmts["header"])
    row += 1
    for item in val.blended_target.methodology_weights if val.blended_target else []:
        ws.write(row, 0, item.name, fmts["body"])
        if item.weight is not None:
            ws.write_number(row, 1, float(item.weight), fmts["pct"])
        if item.implied_price is not None:
            ws.write_number(row, 2, float(item.implied_price), fmts["money"])
        if item.weighted_contribution is not None:
            ws.write_number(row, 3, float(item.weighted_contribution), fmts["money"])
        row += 1
    row += 1
    ws.write_row(row, 0, ["Quality Flags", "", "", ""], fmts["subheader"])
    row += 1
    for flag in val.blended_target.quality_flags if val.blended_target else []:
        fmt = fmts["warning"] if flag.severity != "note" else fmts["body"]
        ws.write_row(row, 0, [flag.severity.upper(), flag.field, flag.message, ""], fmt)
        row += 1
    row += 1
    ws.write_row(row, 0, ["Investment Thesis", "", "", ""], fmts["subheader"])
    row += 1
    bullets = []
    if val.news:
        bullets.extend(val.news.catalysts[:3])
        bullets.extend([f"Concern: {x}" for x in val.news.concerns[:2]])
        bullets.append(val.news.summary)
    elif risk:
        bullets.extend(risk.assessment.top_risks[:3])
        bullets.append(risk.assessment.summary)
    else:
        bullets.append("No thesis synthesis available.")
    for bullet in bullets[:6]:
        ws.write(row, 0, bullet, fmts["body"])
        row += 1


def _dcf_model(ws: xlsxwriter.worksheet.Worksheet, val: ValuationBundle, fmts) -> None:
    row = _sheet_header(ws, "DCF Model", "Forecast and valuation bridge", fmts)
    headers = ["Metric"] + [f"Year {p.year}" for p in val.dcf.projections] + ["Terminal"]
    ws.write_row(row, 0, headers, fmts["header"])
    row += 1
    lines = [
        ("Revenue", [_money(p.revenue) for p in val.dcf.projections], _money(val.dcf.projections[-1].revenue if val.dcf.projections else None), fmts["money"]),
        ("Revenue Growth %", [_pct(g) for g in val.dcf.assumptions.revenue_growth], _pct(val.dcf.assumptions.terminal_growth), fmts["pct"]),
        ("EBIT", [_money(p.ebit) for p in val.dcf.projections], _money(val.dcf.projections[-1].ebit if val.dcf.projections else None), fmts["money"]),
        ("EBIT Margin %", [_pct(val.dcf.assumptions.ebit_margin) for _ in val.dcf.projections], _pct(val.dcf.assumptions.ebit_margin), fmts["pct"]),
        ("Tax", [_pct(val.dcf.assumptions.tax_rate) for _ in val.dcf.projections], _pct(val.dcf.assumptions.tax_rate), fmts["pct"]),
        ("NOPAT", [_money(p.nopat) for p in val.dcf.projections], _money(val.dcf.projections[-1].nopat if val.dcf.projections else None), fmts["money"]),
        ("Reinvestment", [_money(p.reinvestment) for p in val.dcf.projections], None, fmts["money"]),
        ("FCFF", [_money(p.fcff) for p in val.dcf.projections], None, fmts["money"]),
        ("Discount Factor", [_pct(p.discount_factor) for p in val.dcf.projections], None, fmts["pct"]),
        ("PV FCFF", [_money(p.pv_fcff) for p in val.dcf.projections], None, fmts["money"]),
    ]
    for label, values, terminal, fmt in lines:
        ws.write(row, 0, label, fmts["subheader"])
        for col, value in enumerate(values, start=1):
            if value is not None:
                ws.write_number(row, col, value, fmt)
        if terminal is not None:
            ws.write_number(row, len(values) + 1, terminal, fmt)
        row += 1
    row += 1
    for label, value, fmt in [
        ("PV Explicit", _money(val.dcf.pv_explicit), fmts["money"]),
        ("PV Terminal", _money(val.dcf.pv_terminal), fmts["money"]),
        ("Enterprise Value", _money(val.dcf.enterprise_value), fmts["money"]),
        ("Net Debt", _money(val.dcf.net_debt), fmts["money"]),
        ("Equity Value", _money(val.dcf.equity_value), fmts["money"]),
        ("Shares", _money(val.dcf.shares_outstanding), fmts["money"]),
        ("Implied Price", _money(val.dcf.implied_share_price), fmts["money"]),
    ]:
        ws.write(row, 0, label, fmts["subheader"])
        if value is not None:
            ws.write_number(row, 1, value, fmt)
        row += 1
    row += 1
    ws.write_row(row, 0, ["WACC Breakdown", "", "", ""], fmts["subheader"])
    row += 1
    for label, value, fmt in [
        ("Cost of Equity", _pct(val.dcf.wacc.cost_of_equity), fmts["pct"]),
        ("Cost of Debt", _pct(val.dcf.wacc.cost_of_debt_after_tax), fmts["pct"]),
        ("Weight Equity", _pct(val.dcf.wacc.weight_equity), fmts["pct"]),
        ("Weight Debt", _pct(val.dcf.wacc.weight_debt), fmts["pct"]),
        ("WACC", _pct(val.dcf.wacc.wacc), fmts["pct"]),
    ]:
        ws.write(row, 0, label, fmts["body"])
        if value is not None:
            ws.write_number(row, 1, value, fmt)
        row += 1


def _comps(ws: xlsxwriter.worksheet.Worksheet, comps: CompsResult | None, fmts) -> None:
    row = _sheet_header(ws, "Comps", "Target vs peers and median multiples", fmts)
    ws.write_row(row, 0, ["Ticker", "Mkt Cap", "P/E", "EV/EBITDA", "EV/EBIT", "EV/Revenue", "EV/FCF", "P/Book"], fmts["header"])
    row += 1
    if comps is None:
        ws.write(row, 0, "No comps available", fmts["body"])
        return
    target_map = {item.name: item.target for item in comps.multiples}
    ws.write_row(row, 0, [comps.target, None, target_map.get("P/E"), target_map.get("EV/EBITDA"), target_map.get("EV/EBIT"), target_map.get("EV/Revenue"), target_map.get("EV/FCF"), target_map.get("P/Book")], fmts["gold"])
    row += 1
    for peer in comps.peers:
        ws.write_row(row, 0, [peer.symbol, _money(peer.market_cap), _money(peer.pe_ratio), _money(peer.ev_ebitda), _money(peer.ev_ebit), _money(peer.ev_revenue), _money(peer.ev_fcf), _money(peer.p_book)], fmts["body"])
        row += 1
    median_map = {item.name: item.peer_median for item in comps.multiples}
    ws.write_row(row, 0, ["Median", None, _money(median_map.get("P/E")), _money(median_map.get("EV/EBITDA")), _money(median_map.get("EV/EBIT")), _money(median_map.get("EV/Revenue")), _money(median_map.get("EV/FCF")), _money(median_map.get("P/Book"))], fmts["subheader"])


def _scenarios(ws: xlsxwriter.worksheet.Worksheet, val: ValuationBundle, fmts) -> None:
    row = _sheet_header(ws, "Scenarios", "Bull / base / bear side by side", fmts)
    ws.write_row(row, 0, ["Metric", "Bull", "Base", "Bear"], fmts["header"])
    row += 1
    if val.scenarios is None:
        ws.write(row, 0, "Scenarios unavailable", fmts["body"])
        return
    ws.write_row(row, 0, ["Implied Price", _money(val.scenarios.bull.implied_price), _money(val.scenarios.base.implied_price), _money(val.scenarios.bear.implied_price)], fmts["body"])
    row += 1
    ws.write_row(row, 0, ["Upside %", _pct(val.scenarios.bull.upside_pct), _pct(val.scenarios.base.upside_pct), _pct(val.scenarios.bear.upside_pct)], fmts["body"])
    row += 1
    ws.write_row(row, 0, ["Description", val.scenarios.bull.description, val.scenarios.base.description, val.scenarios.bear.description], fmts["body"])


def _sensitivity(ws: xlsxwriter.worksheet.Worksheet, val: ValuationBundle, fmts) -> None:
    row = _sheet_header(ws, "Sensitivity", "WACC x terminal growth heatmap", fmts)
    ws.write_row(row, 0, ["WACC / g"] + [_pct(g) for g in val.sensitivity.growth_axis], fmts["header"])
    row += 1
    cell_map = {(cell.wacc, cell.terminal_growth): _money(cell.implied_price) for cell in val.sensitivity.cells}
    for wacc in val.sensitivity.wacc_axis:
        ws.write(row, 0, _pct(wacc), fmts["body"])
        for col, growth in enumerate(val.sensitivity.growth_axis, start=1):
            value = cell_map.get((wacc, growth))
            if value is not None:
                ws.write_number(row, col, value, fmts["money"])
        row += 1
    ws.conditional_format(4, 1, row - 1, len(val.sensitivity.growth_axis), {
        "type": "3_color_scale",
        "min_color": "#FCA5A5",
        "mid_color": "#FFFFFF",
        "max_color": "#86EFAC",
    })


def _assumptions(ws: xlsxwriter.worksheet.Worksheet, val: ValuationBundle, fmts) -> None:
    row = _sheet_header(ws, "Assumptions", "Editable assumptions with provenance", fmts)
    ws.write_row(row, 0, ["Assumption", "Value", "Provenance"], fmts["header"])
    row += 1
    items = [
        ("Terminal Growth", _pct(val.dcf.assumptions.terminal_growth), val.provenance.get("terminal_growth", "")),
        ("EBIT Margin", _pct(val.dcf.assumptions.ebit_margin), val.provenance.get("ebit_margin", "")),
        ("WACC", _pct(val.dcf.wacc.wacc), val.provenance.get("wacc", "")),
        ("Revenue Growth Y1", _pct(val.dcf.assumptions.revenue_growth[0]), val.provenance.get("revenue_growth", "")),
    ]
    for label, value, provenance in items:
        ws.write(row, 0, label, fmts["input"])
        if value is not None:
            ws.write_number(row, 1, value, fmts["input"])
        ws.write(row, 2, provenance, fmts["input"])
        row += 1


def _football_field(
    ws: xlsxwriter.worksheet.Worksheet,
    val: ValuationBundle,
    fmts,
    book: xlsxwriter.Workbook,
) -> None:
    row = _sheet_header(ws, "Football Field", "Methodology low / mid / high", fmts)
    ws.write_row(row, 0, ["Methodology", "Low", "Mid", "High"], fmts["header"])
    row += 1
    rows = val.football_field.rows if val.football_field else []
    if not rows:
        ws.write(row, 0, "Unavailable", fmts["body"])
        return
    for item in rows:
        ws.write(row, 0, item.label, fmts["body"])
        ws.write_number(row, 1, float(item.low), fmts["money"])
        ws.write_number(row, 2, float(item.midpoint), fmts["money"])
        ws.write_number(row, 3, float(item.high), fmts["money"])
        row += 1
    chart = book.add_chart({"type": "bar"})
    chart.add_series({"name": "Mid", "categories": [ws.name, 4, 0, row - 1, 0], "values": [ws.name, 4, 2, row - 1, 2], "fill": {"color": "#1E3A5F"}})
    chart.set_title({"name": "Football Field Midpoints"})
    chart.set_legend({"none": True})
    ws.insert_chart("F4", chart)


def build_xlsx(
    path: str | Path,
    val: ValuationBundle,
    comps: CompsResult | None = None,
    risk: RiskOutput | None = None,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    book = xlsxwriter.Workbook(str(path))
    fmts = _formats(book)

    cover = book.add_worksheet("Cover")
    exec_summary = book.add_worksheet("Executive Summary")
    dcf = book.add_worksheet("DCF Model")
    comps_ws = book.add_worksheet("Comps")
    scenarios = book.add_worksheet("Scenarios")
    sensitivity = book.add_worksheet("Sensitivity")
    assumptions = book.add_worksheet("Assumptions")
    football = book.add_worksheet("Football Field")

    for ws in [cover, exec_summary, dcf, comps_ws, scenarios, sensitivity, assumptions, football]:
        ws.set_column("A:H", 18)

    _cover(cover, val, fmts)
    _executive_summary(exec_summary, val, risk, fmts)
    _dcf_model(dcf, val, fmts)
    _comps(comps_ws, comps, fmts)
    _scenarios(scenarios, val, fmts)
    _sensitivity(sensitivity, val, fmts)
    _assumptions(assumptions, val, fmts)
    _football_field(football, val, fmts, book)

    for ws in [cover, exec_summary, dcf, comps_ws, scenarios, sensitivity, football]:
        ws.protect(SHEET_PASSWORD)

    book.close()
    return path
