import type { ReactNode } from "react";

function cn(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

export function Shell({ children }: { children: ReactNode; kicker?: string }) {
  return (
    <div className="min-h-screen bg-[var(--bg)]">
      {/* Top chrome bar */}
      <header className="sticky top-0 z-40 border-b border-[var(--border)] bg-[var(--bg)]/90 backdrop-blur-sm">
        <div className="mx-auto flex max-w-[1440px] items-center gap-4 px-6 py-3 md:px-10">
          <a href="/" className="flex items-center gap-2.5 shrink-0">
            <div className="flex h-7 w-7 items-center justify-center rounded bg-[var(--accent)] text-[10px] font-bold tracking-wider text-white">
              AA
            </div>
            <span className="hidden text-[13px] font-semibold text-[var(--ink)] sm:block">AlphaArchitect</span>
            <span className="hidden text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--muted)] sm:block">Terminal</span>
          </a>
          <div className="mx-2 h-4 w-px bg-[var(--border-strong)]" />
          <nav className="flex items-center gap-1">
            {[
              { href: "/", label: "Dashboard" },
              { href: "/screen", label: "Screener" },
              { href: "/hunter", label: "Hunter" },
            ].map(({ href, label }) => (
              <a
                key={href}
                href={href}
                className="rounded px-3 py-1.5 text-[12px] font-medium text-[var(--muted)] transition-colors hover:bg-[var(--surface-raise)] hover:text-[var(--ink)]"
              >
                {label}
              </a>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-[1440px] px-6 py-8 md:px-10 md:py-10">
        {children}
      </main>
    </div>
  );
}

export function PageIntro({
  eyebrow,
  title,
  description,
  actions,
  meta,
}: {
  eyebrow: string;
  title: string;
  description?: string;
  actions?: ReactNode;
  meta?: ReactNode;
}) {
  return (
    <div className="border-b border-[var(--border)] pb-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="research-label mb-2">{eyebrow}</p>
          <h1 className="text-2xl font-semibold leading-snug text-[var(--ink)] md:text-3xl">
            {title}
          </h1>
          {description && (
            <p className="mt-2 text-sm text-[var(--muted)]">{description}</p>
          )}
          {meta && <div className="mt-3">{meta}</div>}
        </div>
        {actions && (
          <div className="flex flex-shrink-0 flex-wrap items-center gap-2">
            {actions}
          </div>
        )}
      </div>
    </div>
  );
}

export function SectionHead({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-4 flex items-end justify-between gap-4 border-b border-[var(--border)] pb-3">
      <div>
        <p className="research-label">{title}</p>
        {subtitle && <p className="mt-1 text-xs text-[var(--muted)]">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

export function Card({
  title,
  subtitle,
  children,
  className,
  action,
}: {
  title?: string;
  subtitle?: string;
  children: ReactNode;
  className?: string;
  action?: ReactNode;
}) {
  return (
    <section
      className={cn(
        "rounded-xl border border-[var(--border)] bg-[var(--surface)]",
        className,
      )}
    >
      {(title || subtitle) && (
        <div className="flex items-start justify-between gap-3 border-b border-[var(--border)] px-5 py-3.5">
          <div>
            {title && <p className="research-label">{title}</p>}
            {subtitle && <p className="mt-1 text-xs text-[var(--muted)]">{subtitle}</p>}
          </div>
          {action}
        </div>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

export function Stat({
  label,
  value,
  detail,
  tone = "default",
  size = "md",
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: "default" | "positive" | "negative" | "accent" | "warning";
  size?: "sm" | "md" | "lg";
}) {
  const valueColor =
    tone === "positive" ? "text-[var(--positive-text)]"
    : tone === "negative" ? "text-[var(--negative-text)]"
    : tone === "accent" ? "text-[var(--accent-text)]"
    : tone === "warning" ? "text-[var(--caution-text)]"
    : "text-[var(--ink)]";

  const valueSize =
    size === "lg" ? "text-3xl"
    : size === "sm" ? "text-lg"
    : "text-2xl";

  return (
    <div className="border-b border-[var(--border)] py-3 last:border-b-0">
      <p className="research-label">{label}</p>
      <p className={cn("mt-1.5 font-semibold tabular-nums", valueSize, valueColor)}>
        {value}
      </p>
      {detail && <p className="mt-1 text-xs text-[var(--muted)]">{detail}</p>}
    </div>
  );
}

export function StatGrid({ children }: { children: ReactNode }) {
  return (
    <div className="divide-y divide-[var(--border)] rounded-xl border border-[var(--border)] bg-[var(--surface)]">
      <div className="px-5">{children}</div>
    </div>
  );
}

export function KV({ k, v, mono }: { k: string; v: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-6 border-b border-[var(--border)] py-2.5 last:border-b-0">
      <span className="shrink-0 text-xs text-[var(--muted)]">{k}</span>
      <span className={cn("text-right text-sm text-[var(--ink)]", mono && "tabular-nums font-mono")}>
        {v}
      </span>
    </div>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "positive" | "negative" | "warning" | "accent";
}) {
  const cls =
    tone === "positive" ? "bg-[var(--positive-bg)] text-[var(--positive-text)] border-[var(--positive-border)]"
    : tone === "negative" ? "bg-[var(--negative-bg)] text-[var(--negative-text)] border-[var(--negative-border)]"
    : tone === "warning" ? "bg-[var(--caution-bg)] text-[var(--caution-text)] border-[var(--caution-border)]"
    : tone === "accent" ? "bg-[var(--accent-dim)] text-[var(--accent-text)] border-[rgba(99,102,241,0.25)]"
    : "bg-[var(--surface-raise)] text-[var(--muted)] border-[var(--border-strong)]";

  return (
    <span className={cn("inline-flex items-center rounded border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em]", cls)}>
      {children}
    </span>
  );
}

export function Divider({ label }: { label?: string }) {
  if (!label) return <div className="my-6 border-t border-[var(--border)]" />;
  return (
    <div className="relative my-6">
      <div className="absolute inset-0 flex items-center">
        <div className="w-full border-t border-[var(--border)]" />
      </div>
      <div className="relative flex justify-start">
        <span className="bg-[var(--bg)] pr-3 research-label">{label}</span>
      </div>
    </div>
  );
}
