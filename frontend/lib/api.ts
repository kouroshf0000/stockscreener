export const apiBase =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "";

export async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, { ...init, cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return (await r.json()) as T;
}

export const fmtMoney = (v: number | string | null | undefined) =>
  v == null ? "—" : `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

export const fmtPct = (v: number | string | null | undefined) =>
  v == null ? "—" : `${(Number(v) * 100).toFixed(2)}%`;

export const fmtNum = (v: number | string | null | undefined) =>
  v == null ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 });
