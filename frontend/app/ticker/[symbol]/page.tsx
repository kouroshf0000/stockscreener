"use client";

import Link from "next/link";
import { use, useState } from "react";
import useSWR from "swr";
import { Badge, KV, Shell } from "@/components/Shell";
import { fetchJSON, fmtMoney, fmtNum, fmtPct } from "@/lib/api";

/* ─── Types ──────────────────────────────────────────────────── */
type Fundamentals = { ticker: string; name: string | null; sector: string | null; industry: string | null };
type MethodologyWeight = { name: string; weight: string; implied_price: string | null; weighted_contribution: string | null };
type QualityFlag = { severity: "critical" | "warning" | "note"; field: string; message: string };
type MultipleStat = { name: string; target: string | null; peer_median: string | null; peer_weighted: string | null; premium_discount: string | null; implied_price: string | null };
type PeerRow = { symbol: string; market_cap: string | null; pe_ratio: string | null; ev_ebitda: string | null; ev_ebit: string | null; ev_revenue: string | null; ev_fcf: string | null; p_book: string | null };
type Comps = { target: string; peers: PeerRow[]; multiples: MultipleStat[] };
type Projection = { year: number; revenue: string; ebit: string; nopat: string; reinvestment: string; fcff: string; discount_factor: string; pv_fcff: string };
type FootballFieldRow = { label: string; low: string; high: string; midpoint: string };
type GapDriver = { category: string; signal: string; impact: "widening" | "countervailing" | "mixed"; weight: "high" | "medium" | "low"; detail: string };
type GapAnalysis = { triggered: boolean; threshold_pct: string; gap_pct: string | null; target_price: string | null; current_price: string | null; direction: "undervalued" | "overvalued" | "aligned" | "unknown"; severity: "low" | "moderate" | "high"; headline: string; summary: string; industry_context: string; primary_explanation: string; drivers: GapDriver[]; monitoring_points: string[] };
type Bundle = {
  dcf: { ticker: string; as_of: string; current_price: string | null; implied_share_price: string; upside_pct: string | null; enterprise_value: string; equity_value: string; pv_explicit: string; pv_terminal: string; shares_outstanding: string; red_flags: string[]; assumptions: { terminal_growth: string; ebit_margin: string; revenue_growth: string[] }; wacc: { wacc: string; cost_of_equity: string; cost_of_debt_after_tax: string; weight_equity: string; weight_debt: string }; projections: Projection[] };
  provenance: Record<string, string>;
  scenarios: { bull: { implied_price: string; upside_pct: string | null; description: string }; base: { implied_price: string; upside_pct: string | null; description: string }; bear: { implied_price: string; upside_pct: string | null; description: string } } | null;
  comps: Comps | null;
  technicals: { price: string; sma_50: string | null; sma_200: string | null; rsi_14: string | null; macd: string | null; macd_signal: string | null; macd_hist: string | null; w52_high: string | null; w52_low: string | null; distance_from_52w_high: string | null; distance_from_52w_low: string | null; rel_strength_vs_spx: string | null; trend: "uptrend" | "downtrend" | "consolidation"; tv_recommendation: "STRONG_BUY" | "BUY" | "NEUTRAL" | "SELL" | "STRONG_SELL" | null; bb_upper: string | null; bb_lower: string | null; bb_pct_b: string | null; adx: string | null; atr: string | null; patterns: string[] } | null;
  news: { sentiment: "bullish" | "neutral" | "bearish"; score: number; catalysts: string[]; concerns: string[]; summary: string; source: "haiku" | "fallback" } | null;
  football_field: { current_price: string | null; rows: FootballFieldRow[] } | null;
  blended_target: { price: string | null; upside_pct: string | null; current_price: string | null; rating: "OUTPERFORM" | "NEUTRAL" | "UNDERPERFORM" | null; confidence: "high" | "medium" | "low"; methodology_weights: MethodologyWeight[]; quality_flags: QualityFlag[]; regime: string; methodology_note: string | null } | null;
  gap_analysis: GapAnalysis | null;
  sensitivity: SensitivityTable | null;
  monte_carlo: MonteCarlo | null;
  audit: AuditFinding[];
};
type BacktestTrade = { date: string; action: "buy" | "sell"; price: string; pnl_pct: string | null };
type BacktestResult = { ticker: string; strategy: string; lookback_days: number; total_return_pct: string; cagr_pct: string; sharpe_ratio: string | null; max_drawdown_pct: string; win_rate_pct: string; total_trades: number; trades: BacktestTrade[]; disclaimer: string };
type Risk = { source: "haiku" | "fallback"; discount_rate_adjustment: string; fallback_reason: string | null; filing_accession: string | null; filing_form: string | null; filing_date: string | null; filing_url: string | null; risk_factors_chars: number | null; assessment: { legal_risk: number; regulatory_risk: number; macro_risk: number; competitive_risk: number; summary: string; top_risks: string[] } };
type SensitivityCell = { wacc: string; terminal_growth: string; implied_price: string };
type SensitivityTable = { wacc_axis: string[]; growth_axis: string[]; cells: SensitivityCell[] };
type MonteCarlo = { iterations: number; p10: string; p25: string; p50: string; p75: string; p90: string; mean: string; std_dev: string };
type AuditFinding = { rule: string; ok: boolean; detail: string };

/* ─── Helpers ─────────────────────────────────────────────────── */
function cn(...parts: Array<string | false | null | undefined>) { return parts.filter(Boolean).join(" "); }
const num = (v: string | number | null | undefined) => v == null ? null : Number(v);
const posneg = (v: number | null) => v == null ? "text-[var(--ink)]" : v > 0 ? "text-[var(--green)]" : v < 0 ? "text-[var(--red)]" : "text-[var(--ink)]";

function ratingTone(r: "OUTPERFORM" | "NEUTRAL" | "UNDERPERFORM" | null) {
  if (r === "OUTPERFORM") return "positive" as const;
  if (r === "UNDERPERFORM") return "negative" as const;
  return "warning" as const;
}
function footballRange(rows: FootballFieldRow[], cur: number | null) {
  const ns = rows.flatMap(r => [num(r.low), num(r.high)]).filter((x): x is number => x != null);
  if (cur != null) ns.push(cur);
  const lo = ns.length ? Math.min(...ns) : 0;
  const hi = ns.length ? Math.max(...ns) : 1;
  return { min: lo, max: hi === lo ? lo + 1 : hi };
}

/* ─── Page ────────────────────────────────────────────────────── */
export default function TickerPage({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = use(params);
  const sym = symbol.toUpperCase();

  const { data: fundamentals } = useSWR<Fundamentals>(`/api/v1/fundamentals/${sym}`, fetchJSON);
  const { data: val } = useSWR<Bundle>(`/api/v1/valuate/${sym}?include_monte_carlo=true`, (url: string) => fetchJSON<Bundle>(url, { method: "POST" }));
  const { data: risk } = useSWR<Risk>(`/api/v1/risk/${sym}`, fetchJSON);

  if (!val) {
    return (
      <Shell>
        <div className="flex h-64 items-center justify-center">
          <div className="text-center">
            <div className="mx-auto mb-3 h-5 w-5 animate-spin rounded-full border-2 border-[var(--border-strong)] border-t-[var(--navy)]" />
            <p className="text-sm text-[var(--muted)]">Loading research note for {sym}…</p>
          </div>
        </div>
      </Shell>
    );
  }

  const blended = val.blended_target;
  const technicals = val.technicals;
  const news = val.news;
  const comps = val.comps;
  const scenarios = val.scenarios;
  const currentPrice = num(blended?.current_price ?? val.dcf.current_price);
  const upside = num(blended?.upside_pct ?? val.dcf.upside_pct);
  const footballRows = val.football_field?.rows ?? [];
  const football = footballRange(footballRows, currentPrice);

  const medianPeer: Record<string, string | null> = {};
  for (const m of comps?.multiples ?? []) medianPeer[m.name] = m.peer_median;

  return (
    <Shell>
      {/* ── Note Header ─────────────────────────────────────────── */}
      <div className="border-b border-[var(--border)] pb-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-2 mb-2">
              <Badge tone={ratingTone(blended?.rating ?? null)}>
                {blended?.rating ?? "NEUTRAL"}
              </Badge>
              {blended?.confidence && (
                <Badge tone={blended.confidence === "high" ? "positive" : blended.confidence === "low" ? "negative" : "neutral"}>
                  {blended.confidence} confidence
                </Badge>
              )}
              {fundamentals?.sector && (
                <span className="text-xs text-[var(--muted)]">{fundamentals.sector}</span>
              )}
            </div>
            <h1 className="text-3xl font-semibold leading-tight text-[var(--ink)]">
              {fundamentals?.name ?? sym}
              <span className="ml-3 text-xl font-normal text-[var(--muted)]">{sym}</span>
            </h1>
            {fundamentals?.industry && (
              <p className="mt-1.5 text-sm text-[var(--muted)]">{fundamentals.industry}</p>
            )}
          </div>
          <div className="flex flex-col items-end gap-3">
            <div className="flex gap-2">
              <a className="rounded border border-[var(--navy)] bg-[var(--navy)] px-4 py-2 text-sm font-semibold text-white hover:opacity-90" href={`/api/v1/export/xlsx/${sym}`}>Export XLSX</a>
              <a className="rounded border border-[var(--border-strong)] px-4 py-2 text-sm font-semibold text-[var(--ink)] hover:border-[var(--navy)]" href={`/api/v1/export/pdf/${sym}`}>PDF Memo</a>
            </div>
            <p className="text-xs text-[var(--muted)]">As of {val.dcf.as_of}</p>
          </div>
        </div>
      </div>

      {/* ── Key Metrics Bar ─────────────────────────────────────── */}
      <div className="mt-5 grid grid-cols-2 gap-px border border-[var(--border)] bg-[var(--border)] md:grid-cols-4">
        {[
          { label: "Current Price", value: fmtMoney(currentPrice), color: "" },
          { label: "Price Target", value: fmtMoney(blended?.price ?? val.dcf.implied_share_price), color: "text-[var(--navy)]" },
          { label: "Upside / (Downside)", value: fmtPct(upside), color: posneg(upside) },
          { label: "WACC", value: fmtPct(val.dcf.wacc.wacc), color: "" },
        ].map((m) => (
          <div key={m.label} className="bg-[var(--surface)] px-5 py-4">
            <p className="research-label">{m.label}</p>
            <p className={cn("mt-1.5 text-2xl font-semibold tabular-nums", m.color || "text-[var(--ink)]")}>{m.value}</p>
          </div>
        ))}
      </div>

      {/* ── Quality Flags ───────────────────────────────────────── */}
      {blended?.quality_flags?.length ? (
        <div className="mt-4 space-y-1.5">
          {blended.quality_flags.map((flag, i) => (
            <div key={i} className={cn("flex items-start gap-3 rounded border px-4 py-2.5 text-sm",
              flag.severity === "critical" ? "border-[var(--red-border)] bg-[var(--red-bg)]"
              : flag.severity === "warning" ? "border-[var(--amber-border)] bg-[var(--amber-bg)]"
              : "border-[var(--border)] bg-[var(--surface-dim)]"
            )}>
              <span className={cn("shrink-0 text-[10px] font-bold uppercase tracking-[0.14em] pt-0.5",
                flag.severity === "critical" ? "text-[var(--red)]"
                : flag.severity === "warning" ? "text-[var(--amber)]"
                : "text-[var(--muted)]"
              )}>{flag.severity}</span>
              <span className="text-[var(--ink)]"><span className="font-medium">{flag.field}</span> — {flag.message}</span>
            </div>
          ))}
        </div>
      ) : null}

      {/* ── Valuation Gap ───────────────────────────────────────── */}
      {val.gap_analysis && (
        <div className="mt-6">
          <Section title="Gap Analysis">
            <div className="flex flex-wrap items-center gap-2 mb-4">
              <Badge tone={val.gap_analysis.direction === "undervalued" ? "positive" : val.gap_analysis.direction === "overvalued" ? "negative" : "neutral"}>
                {val.gap_analysis.severity} {val.gap_analysis.direction}
              </Badge>
              <Badge tone="neutral">{fmtPct(val.gap_analysis.gap_pct)} gap</Badge>
              <span className="text-xs text-[var(--muted)]">{val.gap_analysis.headline}</span>
            </div>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {val.gap_analysis.drivers.map((d) => (
                <div key={`${d.category}-${d.signal}`} className="rounded border border-[var(--border)] bg-[var(--surface-dim)] px-3 py-2.5">
                  <div className="flex items-center gap-1.5 mb-1">
                    <span className="text-xs font-semibold text-[var(--ink)]">{d.category}</span>
                    <Badge tone={d.impact === "widening" ? "negative" : d.impact === "countervailing" ? "positive" : "warning"}>{d.impact}</Badge>
                    <Badge tone="neutral">{d.weight}</Badge>
                  </div>
                  <span className="text-xs text-[var(--muted)]">{d.signal}</span>
                </div>
              ))}
            </div>
          </Section>
        </div>
      )}

      {/* ── Valuation Model ─────────────────────────────────────── */}
      <div className="mt-8 grid gap-5 xl:grid-cols-[1.15fr_0.85fr]">
        <Section title="Target Construction" subtitle="Blended price target and methodology weights">
          <div className="mb-5 grid grid-cols-2 gap-px border border-[var(--border)] bg-[var(--border)] sm:grid-cols-4">
            {[
              { label: "Blended Target", value: fmtMoney(blended?.price ?? val.dcf.implied_share_price), color: "text-[var(--navy)]" },
              { label: "Upside", value: fmtPct(upside), color: posneg(upside) },
              { label: "Enterprise Value", value: fmtMoney(val.dcf.enterprise_value), color: "" },
              { label: "Equity Value", value: fmtMoney(val.dcf.equity_value), color: "" },
            ].map((m) => (
              <div key={m.label} className="bg-[var(--surface-dim)] px-4 py-3">
                <p className="research-label">{m.label}</p>
                <p className={cn("mt-1 text-base font-semibold tabular-nums", m.color || "text-[var(--ink)]")}>{m.value}</p>
              </div>
            ))}
          </div>

          <table className="data-table w-full">
            <thead>
              <tr>
                <th>Methodology</th>
                <th>Weight</th>
                <th>Implied Price</th>
                <th>Contribution</th>
              </tr>
            </thead>
            <tbody>
              {(blended?.methodology_weights ?? []).map((row) => (
                <tr key={row.name}>
                  <td>{row.name === "52W" ? "52W Mid" : row.name}</td>
                  <td>{fmtPct(row.weight)}</td>
                  <td>{fmtMoney(row.implied_price)}</td>
                  <td>{fmtMoney(row.weighted_contribution)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {blended?.methodology_note && (
            <aside className="mt-4 border-t border-[var(--border)] pt-4">
              <div className="border-l-2 border-[var(--accent)] pl-4">
                <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--accent-text)] mb-1">Analyst Note</p>
                <p className="text-xs leading-5 text-[var(--muted)] italic">{blended.methodology_note}</p>
              </div>
            </aside>
          )}
        </Section>

        <Section title="DCF Assumptions" subtitle="Intrinsic value model inputs and outputs">
          {/* WACC Visual Bar */}
          <div className="mb-4 pb-4 border-b border-[var(--border)]">
            <p className="research-label mb-2">WACC Composition</p>
            <div className="flex h-5 overflow-hidden rounded" style={{ gap: 0 }}>
              <div
                className="h-full bg-[var(--accent)] flex items-center justify-center text-[9px] font-bold text-white"
                style={{ width: `${Number(val.dcf.wacc.weight_equity) * 100}%` }}
              >
                {(Number(val.dcf.wacc.weight_equity) * 100).toFixed(0)}% Equity
              </div>
              <div
                className="h-full bg-[var(--surface-2)] flex items-center justify-center text-[9px] font-bold text-[var(--muted)]"
                style={{ width: `${Number(val.dcf.wacc.weight_debt) * 100}%` }}
              >
                {(Number(val.dcf.wacc.weight_debt) * 100).toFixed(0)}% Debt
              </div>
            </div>
            <div className="mt-1.5 flex justify-between text-[10px] text-[var(--muted)]">
              <span>Ke = {fmtPct(val.dcf.wacc.cost_of_equity)}</span>
              <span>Kd = {fmtPct(val.dcf.wacc.cost_of_debt_after_tax)} after-tax</span>
            </div>
          </div>
          <KV k="WACC" v={fmtPct(val.dcf.wacc.wacc)} mono />
          <KV k="Terminal Growth" v={fmtPct(val.dcf.assumptions.terminal_growth)} mono />
          <KV k="Initial Revenue Growth" v={fmtPct(val.dcf.assumptions.revenue_growth[0])} mono />
          <KV k="EBIT Margin" v={fmtPct(val.dcf.assumptions.ebit_margin)} mono />
          <KV k="PV Explicit Period" v={fmtMoney(val.dcf.pv_explicit)} mono />
          <KV k="PV Terminal Value" v={fmtMoney(val.dcf.pv_terminal)} mono />
          <KV k="DCF Implied Price" v={<span className={posneg(num(val.dcf.upside_pct))}>{fmtMoney(val.dcf.implied_share_price)}</span>} mono />
          <KV k="Shares Outstanding" v={fmtNum(val.dcf.shares_outstanding)} mono />
          {val.provenance?.sector && (
            <p className="mt-3 text-xs text-[var(--muted)] border-t border-[var(--border)] pt-3">{val.provenance.sector}</p>
          )}
        </Section>
      </div>

      {/* ── Scenario Analysis ───────────────────────────────────── */}
      {scenarios && (
        <div className="mt-8">
          <SectionHead title="Scenario Analysis" subtitle="Bull, base, and bear case under current assumptions" />
          <div className="grid gap-4 md:grid-cols-3">
            {([ ["Bull", scenarios.bull, "positive"], ["Base", scenarios.base, "neutral"], ["Bear", scenarios.bear, "negative"] ] as const).map(([label, s, tone]) => (
              <div key={label} className={cn(
                "rounded-xl border p-5 transition-colors",
                tone === "positive" ? "border-[var(--positive-border)] bg-[var(--positive-dim)]"
                : tone === "negative" ? "border-[var(--negative-border)] bg-[var(--negative-dim)]"
                : "border-[var(--border)] bg-[var(--surface)]"
              )}>
                <Badge tone={tone}>{label}</Badge>
                <p className={cn("mt-3 text-3xl font-semibold tabular-nums font-mono", tone === "positive" ? "text-[var(--positive-text)]" : tone === "negative" ? "text-[var(--negative-text)]" : "text-[var(--ink)]")}>
                  {fmtMoney(s.implied_price)}
                </p>
                <p className={cn("mt-1 text-sm tabular-nums font-mono", posneg(num(s.upside_pct)))}>{fmtPct(s.upside_pct)}</p>
                {s.description && <p className="mt-3 text-xs leading-5 text-[var(--muted)]">{s.description}</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Football Field ──────────────────────────────────────── */}
      {footballRows.length > 0 && (
        <div className="mt-8">
          <SectionHead title="Football Field" subtitle="Valuation methodology ranges vs. current market price" />
          <div className="rounded border border-[var(--border)] bg-[var(--surface)] p-5 space-y-5">
            {footballRows.map((row) => {
              const lo = num(row.low) ?? football.min;
              const hi = num(row.high) ?? football.max;
              const left = ((lo - football.min) / (football.max - football.min)) * 100;
              const width = ((hi - lo) / (football.max - football.min)) * 100;
              const cur = currentPrice == null ? null : ((currentPrice - football.min) / (football.max - football.min)) * 100;
              return (
                <div key={row.label}>
                  <div className="mb-1.5 flex items-center justify-between text-xs">
                    <span className="font-medium text-[var(--ink)]">{row.label}</span>
                    <span className="tabular-nums text-[var(--muted)]">{fmtMoney(row.low)} – {fmtMoney(row.high)}</span>
                  </div>
                  <div className="relative h-8 rounded border border-[var(--border)] bg-[var(--surface-dim)]">
                    <div className="absolute inset-y-1.5 rounded-sm bg-[var(--navy-light)]" style={{ left: `${left}%`, width: `${Math.max(width, 1)}%` }} />
                    {cur != null && <div className="absolute inset-y-0 w-0.5 bg-[var(--red)]" style={{ left: `${cur}%` }} />}
                  </div>
                </div>
              );
            })}
            <p className="text-xs text-[var(--muted)]">Red line = current market price</p>
          </div>
        </div>
      )}

      {/* ── DCF Projections ─────────────────────────────────────── */}
      <div className="mt-8">
        <SectionHead title="DCF Projections" subtitle="Explicit forecast period — revenue, EBIT, and free cash flow to firm" />
        <div className="overflow-x-auto rounded border border-[var(--border)] bg-[var(--surface)]">
          <table className="data-table w-full min-w-[760px]">
            <thead>
              <tr>
                {["Year","Revenue","EBIT","NOPAT","Reinvestment","FCFF","PV FCFF"].map(h => <th key={h}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {val.dcf.projections.map((row) => (
                <tr key={row.year}>
                  <td className="font-medium">{row.year}</td>
                  <td>{fmtMoney(row.revenue)}</td>
                  <td>{fmtMoney(row.ebit)}</td>
                  <td>{fmtMoney(row.nopat)}</td>
                  <td>{fmtMoney(row.reinvestment)}</td>
                  <td>{fmtMoney(row.fcff)}</td>
                  <td className="font-medium text-[var(--navy)]">{fmtMoney(row.pv_fcff)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {val.dcf.red_flags.length > 0 && (
          <div className="mt-3 space-y-1.5">
            {val.dcf.red_flags.map((f) => (
              <div key={f} className="flex items-start gap-2 rounded border border-[var(--amber-border)] bg-[var(--amber-bg)] px-4 py-2.5 text-xs text-[var(--amber-text)]">
                <span className="font-bold uppercase tracking-wider">Flag</span>
                <span>{f}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Sensitivity Table ───────────────────────────────────── */}
      {val.sensitivity && val.sensitivity.cells.length > 0 && (
        <div className="mt-8">
          <SectionHead title="Sensitivity Analysis" subtitle="Implied share price across WACC × terminal growth rate" />
          <div className="overflow-x-auto rounded border border-[var(--border)] bg-[var(--surface)]">
            <table className="w-full min-w-[600px] text-center text-[11px]">
              <thead>
                <tr>
                  <th className="sticky left-0 bg-[var(--surface-dim)] px-3 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wider text-[var(--muted)]">
                    WACC \ g
                  </th>
                  {val.sensitivity.growth_axis.map((g) => (
                    <th key={g} className="px-3 py-2.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--muted)]">
                      {fmtPct(g)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {val.sensitivity.wacc_axis.map((wacc) => (
                  <tr key={wacc}>
                    <td className="sticky left-0 bg-[var(--surface-dim)] px-3 py-2 text-left font-semibold text-[var(--muted)]">
                      {fmtPct(wacc)}
                    </td>
                    {val.sensitivity!.growth_axis.map((g) => {
                      const cell = val.sensitivity!.cells.find(
                        (c) => c.wacc === wacc && c.terminal_growth === g
                      );
                      const price = cell ? Number(cell.implied_price) : null;
                      const diff = price != null && currentPrice ? (price - currentPrice) / currentPrice : null;
                      const bg =
                        diff == null ? "transparent"
                        : diff > 0.3 ? "rgba(34,197,94,0.22)"
                        : diff > 0.1 ? "rgba(34,197,94,0.12)"
                        : diff > 0 ? "rgba(34,197,94,0.06)"
                        : diff > -0.1 ? "rgba(239,68,68,0.06)"
                        : diff > -0.3 ? "rgba(239,68,68,0.12)"
                        : "rgba(239,68,68,0.22)";
                      const textColor =
                        diff == null ? "var(--ink-secondary)"
                        : diff > 0.1 ? "var(--positive-text)"
                        : diff < -0.1 ? "var(--negative-text)"
                        : "var(--ink)";
                      return (
                        <td key={g} className="px-3 py-2 font-mono tabular-nums" style={{ background: bg, color: textColor }}>
                          {price != null ? `$${price.toFixed(0)}` : "—"}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Monte Carlo ─────────────────────────────────────────── */}
      {val.monte_carlo && (
        <div className="mt-8">
          <SectionHead title="Monte Carlo Distribution" subtitle={`${val.monte_carlo.iterations.toLocaleString()} simulations — implied price percentile range`} />
          <div className="rounded border border-[var(--border)] bg-[var(--surface)] p-5">
            <MonteCarloBar mc={val.monte_carlo} currentPrice={currentPrice} />
          </div>
        </div>
      )}

      {/* ── Risk and Technicals ─────────────────────────────────── */}
      <div className="mt-8 grid gap-5 xl:grid-cols-[1fr_1fr]">
        <Section title="Risk Assessment" subtitle={risk?.source === "haiku" ? "Scored from SEC 10-K filing via Claude" : "Fallback — no filing available"}>
          {risk && (
            <>
              <div className="mb-4 flex flex-wrap items-center gap-2">
                <Badge tone={risk.source === "haiku" ? "positive" : "warning"}>
                  {risk.source === "haiku" ? "10-K Scored" : "Fallback"}
                </Badge>
                <span className="text-xs text-[var(--muted)]">
                  DR adjustment {fmtPct(risk.discount_rate_adjustment)}
                </span>
              </div>
              <div className="space-y-3 mb-4">
                {([ ["Legal", risk.assessment.legal_risk], ["Regulatory", risk.assessment.regulatory_risk], ["Macro", risk.assessment.macro_risk], ["Competitive", risk.assessment.competitive_risk] ] as const).map(([label, val]) => (
                  <div key={label}>
                    <div className="mb-1 flex items-center justify-between text-xs">
                      <span className="text-[var(--muted)]">{label}</span>
                      <span className="font-medium text-[var(--ink)]">{val}/3</span>
                    </div>
                    <div className="h-1.5 rounded-full bg-[var(--surface-dim)]">
                      <div className={cn("h-full rounded-full", val >= 3 ? "bg-[var(--red)]" : val === 2 ? "bg-[var(--amber)]" : "bg-[var(--green)]")} style={{ width: `${(val / 3) * 100}%` }} />
                    </div>
                  </div>
                ))}
              </div>
              {risk.assessment.top_risks?.length > 0 && (
                <ul className="mb-3 space-y-1">
                  {risk.assessment.top_risks.slice(0, 3).map((r: string, i: number) => (
                    <li key={i} className="flex gap-2 text-xs text-[var(--ink-secondary)]">
                      <span className="shrink-0 text-[var(--red)] font-semibold">{i + 1}.</span>{r}
                    </li>
                  ))}
                </ul>
              )}
              {risk.filing_accession && (
                <p className="text-xs text-[var(--muted)]">
                  Source: <a className="text-[var(--navy-text)] underline" href={risk.filing_url ?? "#"} target="_blank" rel="noreferrer">{risk.filing_form} / {risk.filing_accession}</a> ({risk.filing_date})
                </p>
              )}
            </>
          )}
        </Section>

        <Section title="Technical Picture" subtitle="Trend, momentum, and breadth indicators">
          {technicals ? (
            <>
              <div className="mb-4 flex flex-wrap items-center gap-2">
                <Badge tone={technicals.trend === "uptrend" ? "positive" : technicals.trend === "downtrend" ? "negative" : "warning"}>
                  {technicals.trend}
                </Badge>
                {technicals.tv_recommendation && (
                  <Badge tone={technicals.tv_recommendation.includes("BUY") ? "positive" : technicals.tv_recommendation.includes("SELL") ? "negative" : "neutral"}>
                    TV: {technicals.tv_recommendation.replace("_", " ")}
                  </Badge>
                )}
              </div>
              <div className="grid grid-cols-2 gap-x-6">
                <div>
                  <KV k="50-Day SMA" v={fmtMoney(technicals.sma_50)} mono />
                  <KV k="200-Day SMA" v={fmtMoney(technicals.sma_200)} mono />
                  <KV k="RSI (14)" v={fmtNum(technicals.rsi_14)} mono />
                  <KV k="MACD" v={fmtNum(technicals.macd)} mono />
                  <KV k="52W High" v={fmtMoney(technicals.w52_high)} mono />
                  <KV k="52W Low" v={fmtMoney(technicals.w52_low)} mono />
                </div>
                <div>
                  <KV k="BB Upper" v={fmtMoney(technicals.bb_upper)} mono />
                  <KV k="BB Lower" v={fmtMoney(technicals.bb_lower)} mono />
                  <KV k="BB %B" v={fmtNum(technicals.bb_pct_b)} mono />
                  <KV k="ADX" v={fmtNum(technicals.adx)} mono />
                  <KV k="ATR" v={fmtNum(technicals.atr)} mono />
                  <KV k="Rel. Strength vs SPX" v={<span className={posneg(num(technicals.rel_strength_vs_spx))}>{fmtPct(technicals.rel_strength_vs_spx)}</span>} mono />
                </div>
              </div>
              {technicals.patterns?.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {technicals.patterns.map(p => (
                    <span key={p} className="rounded border border-[var(--border)] bg-[var(--surface-dim)] px-2 py-0.5 text-[10px] text-[var(--muted)]">
                      {p.replace("Candle.", "").replace(/_/g, " ")}
                    </span>
                  ))}
                </div>
              )}
            </>
          ) : <p className="text-sm text-[var(--muted)]">Technical data unavailable.</p>}
        </Section>
      </div>

      {/* ── News Sentiment ──────────────────────────────────────── */}
      {news && (
        <div className="mt-8">
          <SectionHead title="News & Sentiment" subtitle={`${news.source === "haiku" ? "Scored via Claude" : "Fallback"} — headline posture`} />
          <div className="rounded border border-[var(--border)] bg-[var(--surface)] p-5">
            <div className="flex items-center gap-3 mb-4">
              <Badge tone={news.sentiment === "bullish" ? "positive" : news.sentiment === "bearish" ? "negative" : "warning"}>
                {news.sentiment}
              </Badge>
              <span className="text-xs text-[var(--muted)]">Score {news.score}</span>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <p className="research-label mb-2">Catalysts</p>
                <ul className="space-y-1.5">
                  {(news.catalysts.length ? news.catalysts : ["No near-term catalysts surfaced."]).map((c, i) => (
                    <li key={i} className="flex gap-2 text-xs leading-5 text-[var(--ink-secondary)]">
                      <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-[var(--green)]" />{c}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="research-label mb-2">Concerns</p>
                <ul className="space-y-1.5">
                  {(news.concerns.length ? news.concerns : ["No headline-driven concerns surfaced."]).map((c, i) => (
                    <li key={i} className="flex gap-2 text-xs leading-5 text-[var(--ink-secondary)]">
                      <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-[var(--red)]" />{c}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Trading Comps ───────────────────────────────────────── */}
      <div className="mt-8">
        <SectionHead title="Trading Comparables" subtitle={`${sym} vs. peer set — current multiples`} />
        <div className="overflow-x-auto rounded border border-[var(--border)] bg-[var(--surface)]">
          <table className="data-table w-full min-w-[900px]">
            <thead>
              <tr>
                {["Ticker","Market Cap","P/E","EV/EBITDA","EV/EBIT","EV/Revenue","EV/FCF","P/Book"].map(h => <th key={h}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              <tr className="bg-[var(--navy-light)]">
                <td className="font-bold text-[var(--navy)]">{sym}</td>
                <td>—</td>
                {["P/E","EV/EBITDA","EV/EBIT","EV/Revenue","EV/FCF","P/Book"].map(n => (
                  <td key={n}>{fmtNum(comps?.multiples.find(m => m.name === n)?.target)}</td>
                ))}
              </tr>
              {(comps?.peers ?? []).map((peer) => (
                <tr key={peer.symbol}>
                  <td><Link href={`/ticker/${peer.symbol}`} className="font-medium text-[var(--navy-text)] hover:underline">{peer.symbol}</Link></td>
                  <td>{fmtMoney(peer.market_cap)}</td>
                  <td>{fmtNum(peer.pe_ratio)}</td>
                  <td>{fmtNum(peer.ev_ebitda)}</td>
                  <td>{fmtNum(peer.ev_ebit)}</td>
                  <td>{fmtNum(peer.ev_revenue)}</td>
                  <td>{fmtNum(peer.ev_fcf)}</td>
                  <td>{fmtNum(peer.p_book)}</td>
                </tr>
              ))}
              <tr className="bg-[var(--surface-dim)] font-medium">
                <td className="text-[var(--muted)]">Peer Median</td>
                <td>—</td>
                {["P/E","EV/EBITDA","EV/EBIT","EV/Revenue","EV/FCF","P/Book"].map(n => (
                  <td key={n}>{fmtNum(medianPeer[n])}</td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Backtest ────────────────────────────────────────────── */}
      <BacktestCard sym={sym} />

      {/* ── Footer ──────────────────────────────────────────────── */}
      <footer className="mt-10 border-t border-[var(--border)] pt-4 text-xs text-[var(--muted)]">
        For professional and informational use only. Not investment advice. Historical performance does not guarantee future results.
        Data sources: SEC EDGAR, Yahoo Finance, Federal Reserve (FRED), TradingView.
        Generated by AlphaArchitect Terminal.
      </footer>
    </Shell>
  );
}

/* ─── Layout helpers ──────────────────────────────────────────── */
function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="rounded border border-[var(--border)] bg-[var(--surface)]">
      <div className="border-b border-[var(--border)] px-5 py-3.5">
        <p className="research-label">{title}</p>
        {subtitle && <p className="mt-0.5 text-xs text-[var(--muted)]">{subtitle}</p>}
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

function SectionHead({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-4 border-b border-[var(--border)] pb-3">
      <p className="research-label">{title}</p>
      {subtitle && <p className="mt-0.5 text-xs text-[var(--muted)]">{subtitle}</p>}
    </div>
  );
}

/* ─── Monte Carlo Bar ─────────────────────────────────────────── */
function MonteCarloBar({ mc, currentPrice }: { mc: MonteCarlo; currentPrice: number | null }) {
  const p10 = Number(mc.p10);
  const p25 = Number(mc.p25);
  const p50 = Number(mc.p50);
  const p75 = Number(mc.p75);
  const p90 = Number(mc.p90);
  const allPts = [p10, p90, ...(currentPrice ? [currentPrice] : [])];
  const min = Math.min(...allPts) * 0.97;
  const max = Math.max(...allPts) * 1.03;
  const span = max - min || 1;
  const pct = (v: number) => `${((v - min) / span) * 100}%`;

  return (
    <div>
      <div className="relative h-10 w-full">
        {/* P10–P90 outer band */}
        <div className="absolute top-3 h-4 rounded bg-[var(--accent-dim)]"
          style={{ left: pct(p10), width: `${((p90 - p10) / span) * 100}%` }} />
        {/* P25–P75 inner band */}
        <div className="absolute top-3 h-4 rounded bg-[var(--accent)]" style={{ opacity: 0.3, left: pct(p25), width: `${((p75 - p25) / span) * 100}%` }} />
        {/* P50 median line */}
        <div className="absolute top-1 h-8 w-0.5 bg-[var(--accent)]" style={{ left: pct(p50) }} />
        {/* Current price */}
        {currentPrice && (
          <div className="absolute top-0 h-10 w-0.5 bg-[var(--negative)]" style={{ left: pct(currentPrice) }} />
        )}
      </div>
      <div className="mt-3 grid grid-cols-5 gap-1 text-center">
        {([["P10", p10], ["P25", p25], ["P50", p50], ["P75", p75], ["P90", p90]] as const).map(([label, v]) => (
          <div key={label}>
            <p className="text-[10px] text-[var(--muted)]">{label}</p>
            <p className="font-mono text-sm font-semibold text-[var(--ink)]">${Number(v).toFixed(0)}</p>
          </div>
        ))}
      </div>
      {currentPrice && (
        <p className="mt-2 text-[10px] text-[var(--muted)]">
          <span className="inline-block w-2.5 h-0.5 bg-[var(--negative)] mr-1 align-middle" />
          Current price ${currentPrice.toFixed(2)}
          <span className="inline-block w-2.5 h-0.5 bg-[var(--accent)] mr-1 align-middle ml-3" />
          P50 median ${p50.toFixed(2)}
        </p>
      )}
    </div>
  );
}

/* ─── Backtest Card ───────────────────────────────────────────── */
const STRATEGIES = [
  { value: "rsi", label: "RSI (30/70)" },
  { value: "macd_cross", label: "MACD Cross" },
  { value: "sma_cross", label: "SMA 50/200" },
  { value: "bb_reversion", label: "BB Reversion" },
];
const LOOKBACKS = [{ label: "1Y", days: 365 }, { label: "2Y", days: 730 }, { label: "3Y", days: 1095 }];

function BacktestCard({ sym }: { sym: string }) {
  const [strategy, setStrategy] = useState("rsi");
  const [lookback, setLookback] = useState(365);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchJSON<BacktestResult>(`/api/v1/backtest/${sym}?strategy=${strategy}&lookback_days=${lookback}`);
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Backtest failed");
    } finally {
      setLoading(false);
    }
  }

  const totalRet = result ? Number(result.total_return_pct) : null;

  return (
    <div className="mt-8">
      <SectionHead title="Signal Backtest" subtitle="Historical strategy simulation — no transaction costs or slippage applied" />
      <div className="rounded border border-[var(--border)] bg-[var(--surface)] p-5">
        {/* Controls */}
        <div className="flex flex-wrap items-end gap-4 mb-5">
          <div>
            <p className="research-label mb-1.5">Strategy</p>
            <select
              className="rounded border border-[var(--border)] bg-[var(--surface-dim)] px-3 py-2 text-sm text-[var(--ink)] outline-none focus:border-[var(--navy)]"
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
            >
              {STRATEGIES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
          <div>
            <p className="research-label mb-1.5">Lookback</p>
            <div className="flex gap-1">
              {LOOKBACKS.map(lb => (
                <button
                  key={lb.days}
                  onClick={() => setLookback(lb.days)}
                  className={cn("rounded border px-3 py-2 text-sm font-medium transition-colors",
                    lookback === lb.days
                      ? "border-[var(--navy)] bg-[var(--navy)] text-white"
                      : "border-[var(--border)] text-[var(--ink)] hover:border-[var(--navy)]"
                  )}
                >
                  {lb.label}
                </button>
              ))}
            </div>
          </div>
          <button
            onClick={run}
            disabled={loading}
            className="flex items-center gap-2 rounded bg-[var(--navy)] px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {loading ? <><span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />Running…</> : "Run Backtest"}
          </button>
        </div>

        {error && (
          <div className="mb-4 rounded border border-[var(--red-border)] bg-[var(--red-bg)] px-4 py-3 text-sm text-[var(--red-text)]">{error}</div>
        )}

        {result && (
          <>
            {/* Metrics */}
            <div className="mb-5 grid grid-cols-2 gap-px border border-[var(--border)] bg-[var(--border)] sm:grid-cols-5">
              {[
                { label: "Total Return", value: fmtPct(result.total_return_pct), color: posneg(totalRet) },
                { label: "CAGR", value: fmtPct(result.cagr_pct), color: "" },
                { label: "Sharpe Ratio", value: fmtNum(result.sharpe_ratio), color: "" },
                { label: "Max Drawdown", value: fmtPct(result.max_drawdown_pct), color: "text-[var(--red)]" },
                { label: "Win Rate", value: fmtPct(result.win_rate_pct), color: "" },
              ].map((m) => (
                <div key={m.label} className="bg-[var(--surface-dim)] px-4 py-3">
                  <p className="research-label">{m.label}</p>
                  <p className={cn("mt-1 text-lg font-semibold tabular-nums", m.color || "text-[var(--ink)]")}>{m.value}</p>
                </div>
              ))}
            </div>

            {/* Trade log */}
            <p className="research-label mb-2">Trade Log — {result.total_trades} closed trade{result.total_trades !== 1 ? "s" : ""}</p>
            <div className="max-h-64 overflow-y-auto rounded border border-[var(--border)]">
              <table className="data-table w-full">
                <thead className="sticky top-0 bg-[var(--surface)]">
                  <tr>
                    <th>Date</th>
                    <th>Action</th>
                    <th>Price</th>
                    <th>P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {result.trades.map((t, i) => (
                    <tr key={i}>
                      <td>{t.date}</td>
                      <td><span className={cn("text-[10px] font-bold uppercase", t.action === "buy" ? "text-[var(--green)]" : "text-[var(--red)]")}>{t.action}</span></td>
                      <td>{fmtMoney(t.price)}</td>
                      <td className={posneg(num(t.pnl_pct))}>{t.pnl_pct ? fmtPct(t.pnl_pct) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-[10px] text-[var(--muted)]">{result.disclaimer}</p>
          </>
        )}
      </div>
    </div>
  );
}
