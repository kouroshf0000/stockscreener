"use client";

import Link from "next/link";
import { useState } from "react";
import { fetchJSON, fmtMoney, fmtNum } from "@/lib/api";

type Filter = { metric: string; op: string; value: number; vs_sector?: boolean };
type Row = {
  symbol: string;
  sector: string | null;
  price: string | null;
  market_cap: string | null;
  metrics: Record<string, string | null>;
};
type ScreenResponse = { total: number; rows: Row[]; etf_overlap: string[] };

const DEFAULT_FILTERS: Filter[] = [
  { metric: "pe_ratio", op: "lt", value: 0.8, vs_sector: true },
  { metric: "revenue_cagr_3y", op: "gt", value: 0.15 },
];

const OPS: { value: string; label: string }[] = [
  { value: "gt", label: ">" },
  { value: "gte", label: "≥" },
  { value: "lt", label: "<" },
  { value: "lte", label: "≤" },
  { value: "eq", label: "=" },
];

const PRESETS: { label: string; filters: Filter[] }[] = [
  {
    label: "Deep Value",
    filters: [
      { metric: "pe_ratio", op: "lt", value: 0.8, vs_sector: true },
      { metric: "fcf_yield", op: "gt", value: 0.05 },
    ],
  },
  {
    label: "Growth",
    filters: [
      { metric: "revenue_cagr_3y", op: "gt", value: 0.2 },
      { metric: "gross_margin", op: "gt", value: 0.4 },
    ],
  },
  {
    label: "Quality",
    filters: [
      { metric: "roe", op: "gt", value: 0.15 },
      { metric: "debt_to_equity", op: "lt", value: 1 },
      { metric: "fcf_yield", op: "gt", value: 0.03 },
    ],
  },
  {
    label: "GARP",
    filters: [
      { metric: "revenue_cagr_3y", op: "gt", value: 0.12 },
      { metric: "pe_ratio", op: "lt", value: 1.2, vs_sector: true },
      { metric: "gross_margin", op: "gt", value: 0.3 },
    ],
  },
];

const COLS = [
  { key: "symbol", label: "Symbol", width: "w-24" },
  { key: "sector", label: "Sector", width: "w-36" },
  { key: "price", label: "Price", width: "w-24" },
  { key: "market_cap", label: "Mkt Cap", width: "w-28" },
  { key: "pe_ratio", label: "P/E", width: "w-20" },
  { key: "ev_ebitda", label: "EV/EBITDA", width: "w-28" },
  { key: "fcf_yield", label: "FCF Yield", width: "w-24" },
  { key: "revenue_cagr_3y", label: "Rev 3Y CAGR", width: "w-32" },
];

function numColor(v: string | null, positiveGood = true): string {
  const n = parseFloat(v ?? "");
  if (isNaN(n)) return "text-[#9598a1]";
  if (positiveGood) return n >= 0 ? "text-[#26a69a]" : "text-[#ef5350]";
  return n >= 0 ? "text-[#ef5350]" : "text-[#26a69a]";
}

export default function ScreenPage() {
  const [filters, setFilters] = useState<Filter[]>(DEFAULT_FILTERS);
  const [etf, setEtf] = useState("");
  const [result, setResult] = useState<ScreenResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchJSON<ScreenResponse>("/api/v1/screen", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ universe: "SP500", filters, etf_overlap: etf || null, limit: 50 }),
      });
      setResult(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }

  function updateFilter(i: number, patch: Partial<Filter>) {
    setFilters((prev) => prev.map((f, j) => (j === i ? { ...f, ...patch } : f)));
  }

  return (
    <div className="flex min-h-screen flex-col bg-[#131722] text-[#d1d4dc]">
      {/* ── Top toolbar ─────────────────────────────────────────── */}
      <div className="border-b border-[#2a2e39] bg-[#1e222d] px-6 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="mr-1 text-xs font-semibold uppercase tracking-widest text-[#787b86]">Screener</span>

          {/* Preset pills */}
          {PRESETS.map((p) => (
            <button
              key={p.label}
              onClick={() => setFilters(p.filters)}
              className="rounded border border-[#2a2e39] bg-[#131722] px-3 py-1 text-xs font-medium text-[#9598a1] transition-colors hover:border-[#434651] hover:text-[#d1d4dc]"
            >
              {p.label}
            </button>
          ))}

          <div className="mx-2 h-4 w-px bg-[#2a2e39]" />

          {/* ETF overlap */}
          <input
            className="w-36 rounded border border-[#2a2e39] bg-[#131722] px-2.5 py-1 text-xs text-[#d1d4dc] placeholder:text-[#4c5059] focus:border-[#2196f3] focus:outline-none"
            value={etf}
            onChange={(e) => setEtf(e.target.value.toUpperCase())}
            placeholder="ETF overlap…"
          />

          <div className="flex-1" />

          {result && (
            <span className="text-xs text-[#787b86]">
              <span className="font-semibold text-[#d1d4dc]">{result.total}</span> results
            </span>
          )}

          <button
            onClick={run}
            disabled={loading || filters.length === 0}
            className="flex items-center gap-2 rounded bg-[#2196f3] px-4 py-1.5 text-xs font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {loading ? (
              <>
                <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                Running…
              </>
            ) : (
              "Run Screen"
            )}
          </button>
        </div>
      </div>

      {/* ── Filter bar ──────────────────────────────────────────── */}
      <div className="border-b border-[#2a2e39] bg-[#1e222d] px-6 py-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[11px] font-semibold uppercase tracking-widest text-[#787b86]">Filters</span>
          {filters.map((f, i) => (
            <div
              key={i}
              className="flex items-center gap-1.5 rounded border border-[#2a2e39] bg-[#131722] pl-2.5 pr-1.5 py-1"
            >
              <input
                className="w-28 bg-transparent text-xs text-[#d1d4dc] placeholder:text-[#4c5059] focus:outline-none"
                value={f.metric}
                onChange={(e) => updateFilter(i, { metric: e.target.value })}
                placeholder="metric"
              />
              <select
                className="bg-transparent text-xs font-mono text-[#2196f3] focus:outline-none cursor-pointer"
                value={f.op}
                onChange={(e) => updateFilter(i, { op: e.target.value })}
              >
                {OPS.map((o) => (
                  <option key={o.value} value={o.value} className="bg-[#1e222d]">{o.label}</option>
                ))}
              </select>
              <input
                type="number"
                step="0.01"
                className="w-16 bg-transparent text-right text-xs tabular-nums text-[#d1d4dc] focus:outline-none"
                value={f.value}
                onChange={(e) => updateFilter(i, { value: Number(e.target.value) })}
              />
              {f.vs_sector && (
                <span className="rounded bg-[#2a2e39] px-1 py-0.5 text-[10px] text-[#787b86]">vs sector</span>
              )}
              <button
                onClick={() => setFilters(filters.filter((_, j) => j !== i))}
                className="ml-0.5 flex h-4 w-4 items-center justify-center rounded text-[#4c5059] transition-colors hover:bg-[#2a2e39] hover:text-[#ef5350]"
              >
                ×
              </button>
            </div>
          ))}
          <button
            onClick={() => setFilters([...filters, { metric: "pe_ratio", op: "lt", value: 20 }])}
            className="rounded border border-dashed border-[#2a2e39] px-2.5 py-1 text-[11px] text-[#787b86] transition-colors hover:border-[#434651] hover:text-[#d1d4dc]"
          >
            + Add
          </button>
        </div>
      </div>

      {/* ── Results table ───────────────────────────────────────── */}
      <div className="flex-1 overflow-auto">
        {error && (
          <div className="m-4 rounded border border-[#ef5350]/30 bg-[#ef5350]/10 px-4 py-3 text-sm text-[#ef5350]">
            {error}
          </div>
        )}

        {result ? (
          <>
            {result.etf_overlap.length > 0 && (
              <div className="border-b border-[#2a2e39] bg-[#1e222d] px-6 py-2 text-xs text-[#787b86]">
                ETF overlap ({etf}): <span className="font-semibold text-[#d1d4dc]">{result.etf_overlap.join(", ")}</span>
              </div>
            )}
            <table className="w-full text-sm">
              <thead className="sticky top-0 z-10 bg-[#1e222d]">
                <tr className="border-b border-[#2a2e39]">
                  {COLS.map((c) => (
                    <th
                      key={c.key}
                      className={`${c.width} px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-[0.14em] text-[#787b86]`}
                    >
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.rows.map((r, idx) => (
                  <tr
                    key={r.symbol}
                    className={`border-b border-[#2a2e39]/60 transition-colors hover:bg-[#2a2e39]/50 ${
                      idx % 2 === 0 ? "" : "bg-[#1a1e2a]"
                    }`}
                  >
                    <td className="px-4 py-2.5">
                      <Link
                        href={`/ticker/${r.symbol}`}
                        className="font-semibold text-[#2196f3] hover:underline"
                      >
                        {r.symbol}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5">
                      {r.sector ? (
                        <span className="rounded bg-[#2a2e39] px-2 py-0.5 text-[11px] text-[#9598a1]">
                          {r.sector}
                        </span>
                      ) : (
                        <span className="text-[#4c5059]">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 tabular-nums text-[#d1d4dc]">{fmtMoney(r.price)}</td>
                    <td className="px-4 py-2.5 tabular-nums text-[#9598a1]">{fmtMoney(r.market_cap)}</td>
                    <td className={`px-4 py-2.5 tabular-nums ${numColor(r.metrics.pe_ratio, false)}`}>
                      {fmtNum(r.metrics.pe_ratio)}
                    </td>
                    <td className={`px-4 py-2.5 tabular-nums ${numColor(r.metrics.ev_ebitda, false)}`}>
                      {fmtNum(r.metrics.ev_ebitda)}
                    </td>
                    <td className={`px-4 py-2.5 tabular-nums ${numColor(r.metrics.fcf_yield)}`}>
                      {fmtNum(r.metrics.fcf_yield)}
                    </td>
                    <td className={`px-4 py-2.5 tabular-nums ${numColor(r.metrics.revenue_cagr_3y)}`}>
                      {fmtNum(r.metrics.revenue_cagr_3y)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : (
          <div className="flex h-64 flex-col items-center justify-center gap-3 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[#2a2e39]">
              <svg className="h-5 w-5 text-[#787b86]" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2a1 1 0 01-.293.707L13 13.414V19a1 1 0 01-.553.894l-4 2A1 1 0 017 21v-7.586L3.293 6.707A1 1 0 013 6V4z" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-medium text-[#9598a1]">No results yet</p>
              <p className="mt-1 text-xs text-[#4c5059]">Configure filters above and hit Run Screen</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
