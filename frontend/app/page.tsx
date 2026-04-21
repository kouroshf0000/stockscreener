import Link from "next/link";

const modules = [
  {
    href: "/screen",
    tag: "Idea Generation",
    title: "Stock Screener",
    description:
      "Filter the S&P 500 and NASDAQ 100 universe on sector-relative valuation, growth, and quality factors. Results link directly into the full research note.",
    icon: (
      <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2a1 1 0 01-.293.707L13 13.414V19a1 1 0 01-.553.894l-4 2A1 1 0 017 21v-7.586L3.293 6.707A1 1 0 013 6V4z" />
      </svg>
    ),
  },
  {
    href: "/hunter",
    tag: "Autonomous Origination",
    title: "Conviction Hunter",
    description:
      "Agent-driven scouting that scores candidates across multiple lenses — value, momentum, quality, growth — and gates picks through a transparent pass/fail conviction check.",
    icon: (
      <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
      </svg>
    ),
  },
  {
    href: "/ticker/NVDA",
    tag: "Single-Name Analysis",
    title: "Research Note",
    description:
      "Full equity brief: DCF with scenario analysis, blended target, trading comps, risk card from 10-K filings, technicals, news sentiment, and backtesting. One URL per name.",
    icon: (
      <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
      </svg>
    ),
  },
];

const stats = [
  { label: "Universe", value: "S&P 500 + NDX" },
  { label: "Valuation Model", value: "DCF + Comps + 52W" },
  { label: "Risk Scoring", value: "10-K NLP (Claude)" },
  { label: "Data Export", value: "XLSX + PDF Memo" },
];

export default function Home() {
  return (
    <div className="min-h-screen bg-[var(--bg)]">
      {/* Top bar */}
      <header className="border-b border-[var(--border)] bg-[var(--bg)]/90 backdrop-blur-sm">
        <div className="mx-auto flex max-w-[1200px] items-center justify-between px-6 py-3 md:px-10">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded bg-[var(--accent)] text-[10px] font-bold tracking-wider text-white">
              AA
            </div>
            <span className="text-[13px] font-semibold text-[var(--ink)]">AlphaArchitect</span>
            <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">Terminal</span>
          </div>
          <nav className="flex items-center gap-1">
            <Link href="/screen" className="rounded px-3 py-1.5 text-[12px] font-medium text-[var(--muted)] transition-colors hover:bg-[var(--surface-raise)] hover:text-[var(--ink)]">Screener</Link>
            <Link href="/hunter" className="rounded px-3 py-1.5 text-[12px] font-medium text-[var(--muted)] transition-colors hover:bg-[var(--surface-raise)] hover:text-[var(--ink)]">Hunter</Link>
            <Link href="/ticker/NVDA" className="rounded px-3 py-1.5 text-[12px] font-medium text-[var(--muted)] transition-colors hover:bg-[var(--surface-raise)] hover:text-[var(--ink)]">Research Note</Link>
          </nav>
        </div>
      </header>

      <div className="mx-auto max-w-[1200px] px-6 py-14 md:px-10 md:py-20">

        {/* Hero */}
        <div className="mb-14">
          <p className="research-label mb-4 text-[var(--accent-text)]">AlphaArchitect Terminal</p>
          <h1 className="text-4xl font-semibold leading-[1.15] tracking-tight text-[var(--ink)] md:text-5xl">
            Institutional-grade equity research<br className="hidden md:block" />
            <span className="text-[var(--muted)]"> at terminal speed.</span>
          </h1>
          <p className="mt-5 max-w-xl text-[15px] leading-7 text-[var(--muted)]">
            Screen, value, and defend equity picks across U.S. public markets. DCF models, trading comps, 10-K risk scoring, and backtesting — all in one URL.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link
              href="/screen"
              className="rounded-lg bg-[var(--accent)] px-5 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
            >
              Open Screener
            </Link>
            <Link
              href="/ticker/NVDA"
              className="rounded-lg border border-[var(--border-strong)] bg-[var(--surface)] px-5 py-2.5 text-sm font-semibold text-[var(--ink)] transition-colors hover:border-[var(--accent)] hover:text-[var(--accent-text)]"
            >
              View Live Note — NVDA →
            </Link>
          </div>
        </div>

        {/* Stats strip */}
        <div className="mb-14 grid grid-cols-2 gap-px rounded-xl border border-[var(--border)] bg-[var(--border)] md:grid-cols-4 overflow-hidden">
          {stats.map((s) => (
            <div key={s.label} className="bg-[var(--surface)] px-6 py-5">
              <p className="research-label mb-1.5">{s.label}</p>
              <p className="text-[15px] font-semibold text-[var(--ink)]">{s.value}</p>
            </div>
          ))}
        </div>

        {/* Module cards */}
        <div>
          <p className="research-label mb-5">Platform Modules</p>
          <div className="grid gap-4 md:grid-cols-3">
            {modules.map((m) => (
              <Link
                key={m.href}
                href={m.href}
                className="group flex flex-col rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6 transition-all duration-150 hover:border-[var(--accent)] hover:bg-[var(--surface-raise)]"
              >
                <div className="mb-4 flex items-center justify-between">
                  <span className="research-label text-[var(--accent-text)]">{m.tag}</span>
                  <span className="text-[var(--faint)] transition-colors group-hover:text-[var(--accent-text)]">
                    {m.icon}
                  </span>
                </div>
                <h2 className="text-[15px] font-semibold text-[var(--ink)] group-hover:text-white">
                  {m.title}
                </h2>
                <p className="mt-3 flex-1 text-[13px] leading-6 text-[var(--muted)]">{m.description}</p>
                <div className="mt-5 flex items-center gap-1 text-xs font-semibold text-[var(--accent-text)] opacity-0 transition-opacity group-hover:opacity-100">
                  Open <span className="ml-0.5">→</span>
                </div>
              </Link>
            ))}
          </div>
        </div>

      </div>
    </div>
  );
}
