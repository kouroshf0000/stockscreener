import { redirect } from "next/navigation";

const RESERVED = new Set(["screen", "hunter", "ticker", "favicon.ico", "api", "_next"]);
const TICKER_RE = /^[A-Za-z][A-Za-z0-9.-]{0,9}$/;

export default async function SymbolShortcut({
  params,
}: {
  params: Promise<{ symbol: string }>;
}) {
  const { symbol } = await params;
  if (RESERVED.has(symbol.toLowerCase()) || !TICKER_RE.test(symbol)) {
    redirect("/");
  }
  redirect(`/ticker/${symbol.toUpperCase()}`);
}
