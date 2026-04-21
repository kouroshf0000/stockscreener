"use client";

import { useState, useEffect, useCallback } from "react";
import { apiBase } from "@/lib/api";

type SignalDirection = "long" | "short" | "no_trade";
type Confidence = "low" | "medium" | "high";

interface TradeSignal {
  direction: SignalDirection;
  confidence: Confidence;
  entry_rationale: string;
  entry_price_note: string;
  stop_loss_note: string;
  target_note: string;
  stop_loss_pct: number;
  target_pct: number;
  risk_reward_estimate: number;
  timeframe_alignment: string;
  key_risks: string[];
  reasoning: string;
}

interface TradePattern {
  pattern: string;
  frequency: number;
  avg_loss_pct: number;
  description: string;
  fix: string;
}

interface ThresholdAdjustment {
  parameter: string;
  current_value: string;
  suggested_value: string;
  rationale: string;
}

interface LossAnalysis {
  analyzed_at: string;
  total_positions_reviewed: number;
  losing_positions: number;
  avg_unrealized_pnl_pct: number;
  patterns: TradePattern[];
  threshold_adjustments: ThresholdAdjustment[];
  overall_assessment: string;
  market_regime_note: string;
}

interface Candidate {
  ticker: string | null;
  side: SignalDirection;
  notional_usd: string;
  conviction_score: string;
  upside_pct: string | null;
  signal: TradeSignal;
  skip_reason: string | null;
}

interface SignalBatch {
  strategy: string;
  quarter: string;
  candidates: Candidate[];
  actionable_count: number;
  skipped_count: number;
}

interface OrderResult {
  ticker: string;
  side: string;
  notional_usd: string;
  order_id: string;
  status: string;
  error: string | null;
}

interface Position {
  ticker: string;
  qty: string;
  market_value: string;
  avg_entry_price: string;
  unrealized_pl: string;
  unrealized_plpc: string;
  side: string;
}

const CONF_COLOR: Record<Confidence, string> = {
  high: "text-emerald-400",
  medium: "text-yellow-400",
  low: "text-zinc-500",
};

const SIDE_COLOR: Record<SignalDirection, string> = {
  long: "text-emerald-400",
  short: "text-red-400",
  no_trade: "text-zinc-500",
};

export default function PaperTradingPage() {
  const [strategy, setStrategy] = useState<"swing" | "day">("swing");
  const [topN, setTopN] = useState(10);
  const [dryRun, setDryRun] = useState(true);
  const [loading, setLoading] = useState(false);
  const [signals, setSignals] = useState<SignalBatch | null>(null);
  const [orders, setOrders] = useState<OrderResult[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [posLoading, setPosLoading] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<LossAnalysis | null>(null);
  const [analyzing, setAnalyzing] = useState(false);

  const fetchPositions = useCallback(async () => {
    setPosLoading(true);
    try {
      const r = await fetch(`${apiBase}/api/v1/trade/paper/positions`);
      if (r.ok) setPositions(await r.json());
    } finally {
      setPosLoading(false);
    }
  }, []);

  useEffect(() => { fetchPositions(); }, [fetchPositions]);

  async function runPipeline() {
    setLoading(true);
    setSignals(null);
    setOrders([]);
    try {
      const url = `${apiBase}/api/v1/trade/paper/run?strategy=${strategy}&top_n=${topN}&dry_run=${dryRun}`;
      const r = await fetch(url, { method: "POST" });
      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();
      setSignals(data.signals);
      setOrders(data.orders);
      if (!dryRun) fetchPositions();
    } catch (e) {
      alert(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function runAnalysis() {
    setAnalyzing(true);
    setAnalysis(null);
    try {
      const r = await fetch(`${apiBase}/api/v1/trade/paper/analyze`, { method: "POST" });
      if (!r.ok) throw new Error(await r.text());
      setAnalysis(await r.json());
    } catch (e) {
      alert(String(e));
    } finally {
      setAnalyzing(false);
    }
  }

  async function closePosition(ticker: string) {
    if (!confirm(`Close position in ${ticker}?`)) return;
    const r = await fetch(`${apiBase}/api/v1/trade/paper/positions/${ticker}`, { method: "DELETE" });
    const data = await r.json();
    if (data.error) alert(data.error);
    fetchPositions();
  }

  const plColor = (v: string) => parseFloat(v) >= 0 ? "text-emerald-400" : "text-red-400";

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100 p-6 max-w-6xl mx-auto">
      <h1 className="text-2xl font-semibold mb-1">Paper Trading</h1>
      <p className="text-zinc-500 text-sm mb-8">
        Conviction screener → DCF gate → Claude trade signal → Alpaca paper orders
      </p>

      {/* Controls */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 mb-6 flex flex-wrap gap-4 items-end">
        <div>
          <label className="text-xs text-zinc-500 block mb-1">Strategy</label>
          <select
            value={strategy}
            onChange={e => setStrategy(e.target.value as "swing" | "day")}
            className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm"
          >
            <option value="swing">Swing (1D + 4H + 1H)</option>
            <option value="day">Day (4H + 1H + 15m)</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-zinc-500 block mb-1">Top N names</label>
          <select
            value={topN}
            onChange={e => setTopN(Number(e.target.value))}
            className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm"
          >
            {[5, 10, 15, 20].map(n => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-zinc-500 block mb-1">Mode</label>
          <div className="flex gap-2">
            <button
              onClick={() => setDryRun(true)}
              className={`px-3 py-2 rounded-lg text-sm border ${dryRun ? "bg-zinc-700 border-zinc-500" : "bg-transparent border-zinc-700 text-zinc-500"}`}
            >
              Dry Run
            </button>
            <button
              onClick={() => setDryRun(false)}
              className={`px-3 py-2 rounded-lg text-sm border ${!dryRun ? "bg-emerald-900 border-emerald-600 text-emerald-300" : "bg-transparent border-zinc-700 text-zinc-500"}`}
            >
              Live Orders
            </button>
          </div>
        </div>
        <div className="ml-auto flex gap-2">
          <button
            onClick={runAnalysis}
            disabled={analyzing}
            className="px-4 py-2 bg-zinc-800 border border-zinc-600 text-zinc-300 font-medium rounded-lg text-sm hover:bg-zinc-700 disabled:opacity-50 disabled:cursor-wait"
          >
            {analyzing ? "Analyzing…" : "Analyze Losses"}
          </button>
          <button
            onClick={runPipeline}
            disabled={loading}
            className="px-5 py-2 bg-white text-zinc-900 font-medium rounded-lg text-sm hover:bg-zinc-200 disabled:opacity-50 disabled:cursor-wait"
          >
            {loading ? "Running pipeline…" : "Run Pipeline"}
          </button>
        </div>
      </div>

      {/* Open Positions */}
      <section className="mb-8">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider">Open Positions</h2>
          <button onClick={fetchPositions} className="text-xs text-zinc-500 hover:text-zinc-300">Refresh</button>
        </div>
        {posLoading ? (
          <p className="text-zinc-600 text-sm">Loading…</p>
        ) : positions.length === 0 ? (
          <p className="text-zinc-600 text-sm">No open positions</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-zinc-500 text-xs border-b border-zinc-800">
                  <th className="text-left py-2">Ticker</th>
                  <th className="text-right py-2">Qty</th>
                  <th className="text-right py-2">Mkt Value</th>
                  <th className="text-right py-2">Avg Entry</th>
                  <th className="text-right py-2">Unr. P&L</th>
                  <th className="text-right py-2">Return</th>
                  <th className="py-2"></th>
                </tr>
              </thead>
              <tbody>
                {positions.map(p => (
                  <tr key={p.ticker} className="border-b border-zinc-800/50 hover:bg-zinc-900/50">
                    <td className="py-3 font-medium">{p.ticker}</td>
                    <td className="text-right text-zinc-400">{parseFloat(p.qty).toFixed(3)}</td>
                    <td className="text-right">${parseFloat(p.market_value).toFixed(2)}</td>
                    <td className="text-right text-zinc-400">${parseFloat(p.avg_entry_price).toFixed(2)}</td>
                    <td className={`text-right ${plColor(p.unrealized_pl)}`}>${parseFloat(p.unrealized_pl).toFixed(2)}</td>
                    <td className={`text-right ${plColor(p.unrealized_plpc)}`}>{(parseFloat(p.unrealized_plpc) * 100).toFixed(2)}%</td>
                    <td className="text-right">
                      <button
                        onClick={() => closePosition(p.ticker)}
                        className="text-xs text-red-500 hover:text-red-400 px-2 py-1"
                      >
                        Close
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Orders from last run */}
      {orders.length > 0 && (
        <section className="mb-8">
          <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider mb-3">Orders Submitted</h2>
          <div className="flex flex-wrap gap-3">
            {orders.map(o => (
              <div key={o.order_id} className={`bg-zinc-900 border rounded-lg px-4 py-3 text-sm ${o.error ? "border-red-800" : "border-zinc-700"}`}>
                <span className="font-medium">{o.ticker}</span>
                <span className={`ml-2 ${o.side === "buy" ? "text-emerald-400" : "text-red-400"}`}>{o.side.toUpperCase()}</span>
                <span className="text-zinc-500 ml-2">${parseFloat(o.notional_usd).toFixed(0)}</span>
                <span className={`ml-2 text-xs ${o.error ? "text-red-400" : "text-zinc-500"}`}>{o.error ?? o.status}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Signal Results */}
      {signals && (
        <section>
          <div className="flex items-center gap-4 mb-4">
            <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider">
              Signals — {signals.quarter}
            </h2>
            <span className="text-xs bg-emerald-900/40 text-emerald-400 border border-emerald-800 px-2 py-0.5 rounded-full">
              {signals.actionable_count} actionable
            </span>
            <span className="text-xs bg-zinc-800 text-zinc-500 px-2 py-0.5 rounded-full">
              {signals.skipped_count} skipped
            </span>
          </div>

          <div className="space-y-3">
            {signals.candidates.map(c => {
              if (!c.ticker) return null;
              const isOpen = expanded === c.ticker;
              return (
                <div key={c.ticker} className={`bg-zinc-900 border rounded-xl overflow-hidden transition-all ${c.side !== "no_trade" ? "border-zinc-700" : "border-zinc-800 opacity-60"}`}>
                  <button
                    className="w-full flex items-center gap-4 px-5 py-4 text-left hover:bg-zinc-800/50"
                    onClick={() => setExpanded(isOpen ? null : c.ticker!)}
                  >
                    <span className="font-semibold w-16">{c.ticker}</span>
                    <span className={`text-sm font-medium uppercase w-16 ${SIDE_COLOR[c.side]}`}>{c.side}</span>
                    <span className="text-xs text-zinc-500">
                      conviction {parseFloat(c.conviction_score).toFixed(1)}
                    </span>
                    {c.upside_pct && (
                      <span className="text-xs text-emerald-400">
                        +{parseFloat(c.upside_pct).toFixed(1)}% DCF upside
                      </span>
                    )}
                    {c.side !== "no_trade" && (
                      <>
                        <span className={`ml-auto text-xs ${CONF_COLOR[c.signal.confidence]}`}>
                          {c.signal.confidence} confidence
                        </span>
                        <span className="text-xs text-zinc-500 ml-3">
                          R:R {c.signal.risk_reward_estimate.toFixed(1)}x
                        </span>
                      </>
                    )}
                    {c.skip_reason && (
                      <span className="ml-auto text-xs text-zinc-600">{c.skip_reason}</span>
                    )}
                    <svg className={`w-4 h-4 text-zinc-600 ml-3 transition-transform ${isOpen ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>

                  {isOpen && c.side !== "no_trade" && (
                    <div className="px-5 pb-5 border-t border-zinc-800 pt-4 space-y-4 text-sm">
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                        <div className="bg-zinc-800/50 rounded-lg p-3">
                          <p className="text-xs text-zinc-500 mb-1">Entry</p>
                          <p className="text-zinc-200">{c.signal.entry_price_note}</p>
                        </div>
                        <div className="bg-zinc-800/50 rounded-lg p-3">
                          <p className="text-xs text-zinc-500 mb-1">Stop Loss</p>
                          <p className="text-zinc-200">{c.signal.stop_loss_note}</p>
                          {c.signal.stop_loss_pct > 0 && (
                            <p className="text-xs text-red-400 mt-1">−{c.signal.stop_loss_pct.toFixed(1)}% from entry</p>
                          )}
                        </div>
                        <div className="bg-zinc-800/50 rounded-lg p-3">
                          <p className="text-xs text-zinc-500 mb-1">Target</p>
                          <p className="text-zinc-200">{c.signal.target_note}</p>
                          {c.signal.target_pct > 0 && (
                            <p className="text-xs text-emerald-400 mt-1">+{c.signal.target_pct.toFixed(1)}% from entry</p>
                          )}
                        </div>
                      </div>
                      <div>
                        <p className="text-xs text-zinc-500 mb-1">Timeframe alignment</p>
                        <p className="text-zinc-300">{c.signal.timeframe_alignment}</p>
                      </div>
                      <div>
                        <p className="text-xs text-zinc-500 mb-1">Reasoning</p>
                        <p className="text-zinc-300 leading-relaxed">{c.signal.reasoning}</p>
                      </div>
                      {c.signal.key_risks.length > 0 && (
                        <div>
                          <p className="text-xs text-zinc-500 mb-2">Key risks</p>
                          <ul className="space-y-1">
                            {c.signal.key_risks.map((r, i) => (
                              <li key={i} className="flex gap-2 text-zinc-400">
                                <span className="text-red-500 mt-0.5">·</span>
                                <span>{r}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}
      {/* Loss Analysis */}
      {analysis && (
        <section className="mt-10">
          <div className="flex items-center gap-3 mb-4">
            <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider">Self-Healing Analysis</h2>
            <span className={`text-xs px-2 py-0.5 rounded-full border ${analysis.losing_positions > 0 ? "bg-red-900/30 text-red-400 border-red-800" : "bg-emerald-900/30 text-emerald-400 border-emerald-800"}`}>
              {analysis.losing_positions} losing / {analysis.total_positions_reviewed} positions
            </span>
          </div>

          {/* Overall assessment */}
          <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-5 mb-4">
            <p className="text-xs text-zinc-500 mb-2 uppercase tracking-wider">Assessment</p>
            <p className="text-zinc-200 leading-relaxed">{analysis.overall_assessment}</p>
            {analysis.market_regime_note && (
              <p className="text-xs text-yellow-400 mt-3 border-t border-zinc-800 pt-3">{analysis.market_regime_note}</p>
            )}
          </div>

          {/* Patterns */}
          {analysis.patterns.length > 0 && (
            <div className="mb-4">
              <p className="text-xs text-zinc-500 uppercase tracking-wider mb-3">Loss Patterns Identified</p>
              <div className="space-y-2">
                {analysis.patterns.map((p, i) => (
                  <div key={i} className="bg-zinc-900 border border-red-900/40 rounded-xl p-4">
                    <div className="flex items-start justify-between gap-4 mb-2">
                      <span className="font-medium text-zinc-200">{p.pattern}</span>
                      <div className="flex gap-3 shrink-0 text-xs">
                        <span className="text-red-400">{p.frequency}× trades</span>
                        <span className="text-red-400">avg −{Math.abs(p.avg_loss_pct).toFixed(1)}%</span>
                      </div>
                    </div>
                    <p className="text-xs text-zinc-400 mb-2">{p.description}</p>
                    <p className="text-xs text-emerald-400 border-t border-zinc-800 pt-2"><span className="text-zinc-500">Fix: </span>{p.fix}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Suggested threshold changes */}
          {analysis.threshold_adjustments.length > 0 && (
            <div>
              <p className="text-xs text-zinc-500 uppercase tracking-wider mb-3">Suggested Adjustments</p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-zinc-500 text-xs border-b border-zinc-800">
                      <th className="text-left py-2">Parameter</th>
                      <th className="text-right py-2">Current</th>
                      <th className="text-right py-2">Suggested</th>
                      <th className="text-left py-2 pl-4">Rationale</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analysis.threshold_adjustments.map((a, i) => (
                      <tr key={i} className="border-b border-zinc-800/50">
                        <td className="py-3 font-mono text-zinc-300">{a.parameter}</td>
                        <td className="text-right text-zinc-500">{a.current_value}</td>
                        <td className="text-right text-yellow-400 font-medium">{a.suggested_value}</td>
                        <td className="pl-4 text-zinc-400 text-xs">{a.rationale}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>
      )}
    </main>
  );
}
