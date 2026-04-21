from __future__ import annotations

ETF_TOP_HOLDINGS: dict[str, list[str]] = {
    "SPY": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "BRK-B", "TSLA", "LLY"],
    "QQQ": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "AVGO", "GOOGL", "GOOG", "COST", "NFLX"],
    "XLK": ["MSFT", "NVDA", "AAPL", "AVGO", "CRM", "ORCL", "AMD", "ADBE", "CSCO", "NOW"],
    "ARKK": ["TSLA", "COIN", "ROKU", "HOOD", "PATH", "PLTR", "RBLX", "DKNG", "CRSP", "NTLA"],
}


def overlap_with(tickers: list[str], etf: str) -> list[str]:
    holdings = ETF_TOP_HOLDINGS.get(etf.upper(), [])
    s = {t.upper() for t in tickers}
    return [h for h in holdings if h in s]
