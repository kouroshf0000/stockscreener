from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest

from backend.data_providers import fred_client


@pytest.mark.asyncio
async def test_fred_fallback_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = fred_client.get_settings()
    monkeypatch.setattr(settings, "fred_api_key", "", raising=False)
    rfr = await fred_client.fetch_risk_free_rate()
    assert rfr.rate == Decimal("0.045")
    assert rfr.series_id == "DGS10"


@pytest.mark.asyncio
async def test_fred_parses_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"observations": [{"date": "2026-04-16", "value": "4.27"}]}

    class _Resp:
        def __init__(self, data: dict) -> None:
            self._data = data
            self.status_code = 200

        def json(self) -> dict:
            return self._data

        def raise_for_status(self) -> None:
            return None

    class _Client:
        def __init__(self, *a: object, **k: object) -> None: ...
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: object) -> None:
            return None

        async def get(self, url: str, params: dict) -> _Resp:
            return _Resp(payload)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    settings = fred_client.get_settings()
    monkeypatch.setattr(settings, "fred_api_key", "testkey", raising=False)
    # Reset module-level daily cache so the mocked HTTP client is actually called
    monkeypatch.setattr(fred_client, "_daily_cache", {})

    rfr = await fred_client.fetch_risk_free_rate()
    assert rfr.rate == Decimal("0.0427")
    assert rfr.as_of == date(2026, 4, 16)
