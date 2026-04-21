from __future__ import annotations

PEER_OVERRIDES: dict[str, list[str]] = {
    "NVDA": ["AMD", "INTC", "AVGO", "QCOM", "TSM"],
    "AMD": ["NVDA", "INTC", "AVGO", "QCOM", "MRVL"],
    "AAPL": ["MSFT", "GOOGL", "META", "AMZN"],
    "MSFT": ["AAPL", "GOOGL", "AMZN", "ORCL", "CRM"],
    "GOOGL": ["META", "MSFT", "AAPL", "AMZN"],
    "META": ["GOOGL", "SNAP", "PINS", "MSFT"],
    "AMZN": ["MSFT", "GOOGL", "WMT", "COST"],
    "TSLA": ["F", "GM", "TM", "RIVN", "NIO"],
    "NFLX": ["DIS", "WBD", "PARA", "CMCSA"],
    "CRM": ["MSFT", "ORCL", "NOW", "ADBE", "SAP"],
    "ORCL": ["MSFT", "CRM", "SAP", "IBM"],
    "JPM": ["BAC", "WFC", "C", "GS", "MS"],
    "XOM": ["CVX", "COP", "SHEL", "BP"],
    "LLY": ["NVO", "PFE", "MRK", "ABBV", "JNJ"],
    "UNH": ["CI", "HUM", "ELV", "CNC"],
    "V": ["MA", "AXP", "PYPL", "FIS"],
    "MA": ["V", "AXP", "PYPL"],
    "WMT": ["TGT", "COST", "KR", "AMZN"],
    "HD": ["LOW", "TSCO", "FND"],
    "COST": ["WMT", "TGT", "BJ"],
    "KO": ["PEP", "MNST", "KDP"],
    "PEP": ["KO", "MDLZ", "MNST"],
}


def peers_for(ticker: str, fallback_sector_peers: list[str] | None = None) -> list[str]:
    sym = ticker.upper()
    if sym in PEER_OVERRIDES:
        return PEER_OVERRIDES[sym]
    return (fallback_sector_peers or [])[:6]
