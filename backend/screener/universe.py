from __future__ import annotations

SP500_STARTER: tuple[str, ...] = (
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "TSLA", "BRK-B", "AVGO",
    "JPM", "LLY", "V", "UNH", "XOM", "MA", "COST", "HD", "PG", "JNJ",
    "WMT", "BAC", "NFLX", "ORCL", "CRM", "ABBV", "CVX", "MRK", "KO", "AMD",
    "ADBE", "PEP", "TMO", "LIN", "ACN", "CSCO", "MCD", "ABT", "DHR", "WFC",
    "TXN", "DIS", "INTU", "VZ", "IBM", "PM", "CAT", "NOW", "QCOM", "ISRG",
)

NDX_STARTER: tuple[str, ...] = (
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "TSLA", "AVGO", "COST",
    "NFLX", "ADBE", "AMD", "PEP", "CSCO", "INTU", "QCOM", "TXN", "CMCSA", "AMGN",
    "HON", "AMAT", "INTC", "BKNG", "SBUX", "GILD", "ADI", "MDLZ", "VRTX", "ADP",
    "REGN", "PANW", "LRCX", "KLAC", "MU", "SNPS", "CDNS", "ASML", "MELI", "CRWD",
)


def universe_for(name: str) -> tuple[str, ...]:
    mapping = {"SP500": SP500_STARTER, "NDX": NDX_STARTER}
    return mapping.get(name.upper(), ())
