from __future__ import annotations

from decimal import Decimal

import pytest

from backend.nlp import risk_analyzer
from backend.nlp.models import RiskAssessment


@pytest.mark.asyncio
async def test_fallback_when_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    s = risk_analyzer.get_settings()
    monkeypatch.setattr(s, "anthropic_api_key", "", raising=False)
    out = await risk_analyzer.analyze_risk("AAPL")
    assert out.source == "fallback"
    assert out.ticker == "AAPL"
    assert out.discount_rate_adjustment == Decimal("4") * risk_analyzer.PER_LEVEL_BPS


@pytest.mark.asyncio
async def test_haiku_path_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    s = risk_analyzer.get_settings()
    monkeypatch.setattr(s, "anthropic_api_key", "sk-test", raising=False)

    from backend.filings import risk_factors as rf_mod
    from backend.filings.risk_factors import RiskExtractionTrace

    async def _fake_universal(_t: str, include_quarterly: bool = False) -> RiskExtractionTrace:
        return RiskExtractionTrace(
            text="Risk factors text about litigation and regulation.",
            reason="ok",
            filing=None,
            doc_url=None,
            chars=50,
            attempts=[],
        )

    monkeypatch.setattr(rf_mod, "fetch_risk_factors_universal", _fake_universal)

    async def _fake_call(_text: str) -> RiskAssessment:
        return RiskAssessment(
            legal_risk=2,
            regulatory_risk=3,
            macro_risk=1,
            competitive_risk=2,
            summary="Mocked assessment.",
            top_risks=["legal", "regulation"],
        )

    monkeypatch.setattr(risk_analyzer, "_call_haiku", _fake_call)

    out = await risk_analyzer.analyze_risk("NVDA")
    assert out.source == "haiku"
    assert out.assessment.legal_risk == 2
    assert out.assessment.regulatory_risk == 3
    expected_adj = min(Decimal(8) * risk_analyzer.PER_LEVEL_BPS, risk_analyzer.MAX_ADJUSTMENT)
    assert out.discount_rate_adjustment == expected_adj
    assert out.discount_rate_adjustment == risk_analyzer.MAX_ADJUSTMENT


@pytest.mark.asyncio
async def test_risk_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    s = risk_analyzer.get_settings()
    monkeypatch.setattr(s, "anthropic_api_key", "", raising=False)
    calls = {"n": 0}

    orig = risk_analyzer._fallback

    def _counted(*args, **kwargs):
        calls["n"] += 1
        return orig(*args, **kwargs)

    monkeypatch.setattr(risk_analyzer, "_fallback", _counted)

    a = await risk_analyzer.analyze_risk("AAPL")
    b = await risk_analyzer.analyze_risk("AAPL")
    assert a == b
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_adjustment_capped() -> None:
    a = RiskAssessment(
        legal_risk=3, regulatory_risk=3, macro_risk=3, competitive_risk=3,
        summary="maxed", top_risks=[],
    )
    adj = risk_analyzer._adjustment_from(a)
    assert adj == risk_analyzer.MAX_ADJUSTMENT
