"use client";

import React, { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { BarChart3, ChevronLeft, ChevronRight, FileText, Search, Telescope, TrendingUp } from "lucide-react";

const NAV = [
  { href: "/", Icon: TrendingUp, label: "Dashboard" },
  { href: "/screen", Icon: BarChart3, label: "Screener" },
  { href: "/hunter", Icon: Telescope, label: "Hunter" },
  { href: "/ticker/NVDA", Icon: FileText, label: "Research Note" },
];

export function AppSidebar({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(true);
  const pathname = usePathname();
  const router = useRouter();
  const [query, setQuery] = useState("");

  function handleSearch(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && query.trim()) {
      router.push(`/ticker/${query.trim().toUpperCase()}`);
      setQuery("");
    }
  }

  return (
    <div className="flex min-h-screen w-full bg-[var(--bg)]">
      {/* Sidebar */}
      <nav
        style={{ width: open ? 220 : 52 }}
        className="sticky top-0 flex h-screen shrink-0 flex-col bg-[#0c1b33] transition-[width] duration-200"
      >
        {/* Brand */}
        <div className="flex items-center gap-3 border-b border-white/10 px-3 py-4">
          <Link href="/" className="flex shrink-0 items-center justify-center">
            <div className="flex h-8 w-8 items-center justify-center rounded bg-[#1e3f78] text-xs font-bold tracking-wider text-white">
              AA
            </div>
          </Link>
          {open && (
            <div className="min-w-0">
              <p className="truncate text-[13px] font-semibold leading-none text-white">
                AlphaArchitect
              </p>
              <p className="mt-1 text-[10px] uppercase tracking-[0.2em] text-white/40">
                Terminal
              </p>
            </div>
          )}
        </div>

        {/* Search */}
        {open && (
          <div className="border-b border-white/10 px-3 py-2.5">
            <div className="flex items-center gap-2 rounded bg-white/8 px-2.5 py-1.5 ring-1 ring-white/10">
              <Search className="h-3.5 w-3.5 shrink-0 text-white/40" />
              <input
                className="min-w-0 flex-1 bg-transparent text-[13px] text-white placeholder:text-white/30 focus:outline-none"
                placeholder="Ticker, e.g. AAPL"
                value={query}
                onChange={(e) => setQuery(e.target.value.toUpperCase())}
                onKeyDown={handleSearch}
              />
            </div>
          </div>
        )}

        {/* Nav */}
        <div className="flex-1 overflow-y-auto py-2">
          {NAV.map(({ href, Icon, label }) => {
            const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                title={!open ? label : undefined}
                className={[
                  "flex h-9 items-center gap-3 px-3 mx-1.5 rounded text-[13px] font-medium transition-colors",
                  active
                    ? "bg-[#1e3f78] text-white"
                    : "text-white/50 hover:bg-white/8 hover:text-white/80",
                ].join(" ")}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {open && <span className="truncate">{label}</span>}
              </Link>
            );
          })}
        </div>

        {/* Divider + collapse */}
        <div className="border-t border-white/10">
          <button
            onClick={() => setOpen(!open)}
            className="flex h-10 w-full items-center gap-3 px-3 text-white/30 transition-colors hover:text-white/60"
          >
            {open ? (
              <>
                <ChevronLeft className="h-4 w-4 shrink-0" />
                <span className="text-[12px]">Collapse</span>
              </>
            ) : (
              <ChevronRight className="h-4 w-4 shrink-0" />
            )}
          </button>
        </div>
      </nav>

      {/* Main content */}
      <div className="min-w-0 flex-1 overflow-auto">{children}</div>
    </div>
  );
}
