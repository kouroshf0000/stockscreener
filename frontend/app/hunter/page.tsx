"use client";

import { useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { Badge, Card, KV, Shell } from "@/components/Shell";
import { fetchJSON, fmtMoney, fmtPct } from "@/lib/api";

type GateCheck = { rule: string; result: "pass" | "fail"; detail: string };
type Pick = {
  ticker: string;
  pick_price: string | null;
  target_price: string | null;
  upside_pct: string | null;
  composite_score: string;
  scout_scores: { scout: string; score: string; evidence: string[] }[];
  gate_checks: GateCheck[];
  gate_passed: boolean;
  thesis_bullets: string[];
  deliverables: { xlsx?: string; pdf?: string };
};
type Report = {
  run_id: string;
  started_at: string;
  finished_at: string;
  candidates_evaluated: number;
  picks: Pick[];
  rejected: Pick[];
};

export default function HunterPage() {
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const { data: history } = useSWR<Report[]>("/api/v1/hunt/history", fetchJSON);

  async function run() {
    setRunning(true);
    try {
      const res = await fetchJSON<Report>("/api/v1/hunt?universe=SP500&top_n=5&limit=20", { method: "POST" });
      setReport(res);
    } finally {
      setRunning(false);
    }
  }

  const r = report ?? history?.[history.length - 1] ?? null;

  return (
    <Shell>
      {/* Header */}
      <div className="border-b border-[var(--border)] pb-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="research-label mb-2">Idea Origination</p>
            <h1 className="font-serif text-4xl font-normal text-[var(--ink)]">Conviction Hunter</h1>
            <p className="mt-2 max-w-xl text-sm text-[var(--muted)]">
              Multi-lens scouting with transparent gate logic. Every pick carries the full evidence trail.
            </p>
          </div>
          <button
            onClick={run}
            disabled={running}
            className="flex items-center gap-2 rounded bg-[var(--navy)] px-5 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {running ? (
              <>
                <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                Running…
              </>
            ) : "Run Hunt"}
          </button>
        </div>
      </div>

      {/* Run summary */}
      {r && (
        <div className="mt-6 grid grid-cols-2 gap-px border border-[var(--border)] bg-[var(--border)] md:grid-cols-4">
          {[
            { label: "Run ID", value: r.run_id.slice(0, 8) },
            { label: "Candidates Evaluated", value: r.candidates_evaluated },
            { label: "Passed Gate", value: r.picks.length },
            { label: "Rejected", value: r.rejected.length },
          ].map((s) => (
            <div key={s.label} className="bg-[var(--surface)] px-4 py-3">
              <p className="research-label">{s.label}</p>
              <p className="mt-1 text-xl font-semibold tabular-nums text-[var(--ink)]">{s.value}</p>
            </div>
          ))}
        </div>
      )}

      {!r ? (
        <div className="mt-8 flex h-48 items-center justify-center rounded border border-dashed border-[var(--border)] bg-[var(--surface)] text-center">
          <div>
            <p className="text-sm font-medium text-[var(--ink)]">No hunt history</p>
            <p className="mt-1 text-xs text-[var(--muted)]">Run the hunt to populate this page.</p>
          </div>
        </div>
      ) : (
        <>
          {/* Picks */}
          {r.picks.length > 0 && (
            <div className="mt-8">
              <p className="research-label mb-4">Picks — Passed Gate</p>
              <div className="grid gap-4 xl:grid-cols-2">
                {r.picks.map((p) => <PickCard key={p.ticker} pick={p} />)}
              </div>
            </div>
          )}

          {/* Rejected */}
          {r.rejected.length > 0 && (
            <div className="mt-8">
              <p className="research-label mb-4">Rejected — Visible for Process Discipline</p>
              <div className="grid gap-4 xl:grid-cols-2">
                {r.rejected.slice(0, 6).map((p) => <PickCard key={p.ticker} pick={p} rejected />)}
              </div>
            </div>
          )}
        </>
      )}
    </Shell>
  );
}

function PickCard({ pick, rejected }: { pick: Pick; rejected?: boolean }) {
  const upside = pick.upside_pct ? Number(pick.upside_pct) : null;

  return (
    <div className={[
      "rounded border bg-[var(--surface)]",
      rejected ? "border-[var(--border)] opacity-75" : "border-[var(--border)]",
    ].join(" ")}>
      {/* Card header */}
      <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-3.5">
        <div className="flex items-center gap-3">
          <Link
            href={`/ticker/${pick.ticker}`}
            className="font-serif text-xl font-normal text-[var(--navy)] hover:underline"
          >
            {pick.ticker}
          </Link>
          <Badge tone={rejected ? "neutral" : "accent"}>
            {rejected ? "Rejected" : "Passed"}
          </Badge>
        </div>
        <span className="text-sm font-semibold tabular-nums text-[var(--ink)]">
          Score {pick.composite_score}
        </span>
      </div>

      <div className="p-5">
        {/* Key metrics */}
        <div className="mb-5 grid grid-cols-3 gap-px border border-[var(--border)] bg-[var(--border)]">
          {[
            { label: "Current Price", value: fmtMoney(pick.pick_price) },
            { label: "Target Price", value: fmtMoney(pick.target_price) },
            { label: "Upside", value: fmtPct(pick.upside_pct), colored: true },
          ].map((m) => (
            <div key={m.label} className="bg-[var(--surface)] px-3 py-2.5">
              <p className="research-label">{m.label}</p>
              <p className={[
                "mt-1 text-lg font-semibold tabular-nums",
                m.colored && upside != null
                  ? upside >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"
                  : "text-[var(--ink)]",
              ].filter(Boolean).join(" ")}>
                {m.value}
              </p>
            </div>
          ))}
        </div>

        {/* Scout scores */}
        <div className="mb-5">
          <p className="research-label mb-3">Scout Stack</p>
          <div className="grid gap-2 sm:grid-cols-2">
            {pick.scout_scores.map((s) => (
              <div key={s.scout} className="rounded border border-[var(--border)] bg-[var(--surface-dim)] px-3 py-2.5">
                <p className="research-label">{s.scout}</p>
                <p className="mt-1 text-xl font-semibold text-[var(--navy)]">{s.score}</p>
                <p className="mt-1.5 text-xs leading-5 text-[var(--muted)]">
                  {s.evidence.slice(0, 2).join(" · ") || "—"}
                </p>
              </div>
            ))}
          </div>
        </div>

        {/* Gate checks */}
        <div className="mb-5">
          <p className="research-label mb-3">Gate Review</p>
          <div className="space-y-1.5">
            {pick.gate_checks.map((g, i) => (
              <div
                key={`${g.rule}-${i}`}
                className={[
                  "rounded border px-3 py-2.5 text-sm",
                  g.result === "pass"
                    ? "border-[var(--green-border)] bg-[var(--green-bg)]"
                    : "border-[var(--red-border)] bg-[var(--red-bg)]",
                ].join(" ")}
              >
                <div className="flex items-center gap-2">
                  <span className={[
                    "text-[10px] font-semibold uppercase tracking-[0.14em]",
                    g.result === "pass" ? "text-[var(--green)]" : "text-[var(--red)]",
                  ].join(" ")}>
                    {g.result}
                  </span>
                  <span className="text-[var(--muted)]">·</span>
                  <span className="text-xs font-medium text-[var(--ink)]">{g.rule}</span>
                </div>
                <p className="mt-1 text-xs text-[var(--muted)]">{g.detail}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Thesis bullets */}
        {pick.thesis_bullets.length > 0 && (
          <div className="mb-5">
            <p className="research-label mb-3">Thesis Highlights</p>
            <ul className="space-y-1.5">
              {pick.thesis_bullets.map((b, i) => (
                <li key={i} className="flex gap-2 text-sm leading-6 text-[var(--ink-secondary)]">
                  <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-[var(--navy)]" />
                  {b}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Exports */}
        {pick.deliverables?.xlsx && (
          <div className="flex gap-2">
            <a
              href={`/api/v1/export/xlsx/${pick.ticker}`}
              className="rounded border border-[var(--navy)] bg-[var(--navy)] px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90"
            >
              XLSX
            </a>
            <a
              href={`/api/v1/export/pdf/${pick.ticker}`}
              className="rounded border border-[var(--border-strong)] px-3 py-1.5 text-xs font-semibold text-[var(--ink)] hover:border-[var(--navy)]"
            >
              PDF Memo
            </a>
          </div>
        )}
      </div>
    </div>
  );
}
