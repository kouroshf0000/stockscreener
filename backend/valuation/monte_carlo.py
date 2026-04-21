from __future__ import annotations

import random
from decimal import Decimal
from statistics import mean, quantiles, stdev

from pydantic import BaseModel, ConfigDict

from backend.data_providers.models import Fundamentals
from backend.valuation.dcf import run_dcf
from backend.valuation.models import Assumptions


class MonteCarloResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    iterations: int
    mean_price: Decimal
    std_price: Decimal
    p10: Decimal
    p50: Decimal
    p90: Decimal


def run_monte_carlo(
    f: Fundamentals,
    base: Assumptions,
    risk_free_rate: Decimal,
    iterations: int = 2_000,
    growth_sigma: float = 0.02,
    margin_sigma: float = 0.02,
    terminal_sigma: float = 0.003,
    seed: int = 42,
) -> MonteCarloResult:
    rng = random.Random(seed)
    prices: list[float] = []
    base_growth = [float(g) for g in base.revenue_growth]
    base_margin = float(base.ebit_margin)
    base_terminal = float(base.terminal_growth)

    for _ in range(iterations):
        growth = [
            max(-0.2, min(0.5, g + rng.gauss(0, growth_sigma))) for g in base_growth
        ]
        margin = max(0.01, min(0.6, base_margin + rng.gauss(0, margin_sigma)))
        term = max(0.0, min(0.04, base_terminal + rng.gauss(0, terminal_sigma)))
        a = Assumptions(
            revenue_growth=[Decimal(str(round(g, 6))) for g in growth],
            ebit_margin=Decimal(str(round(margin, 6))),
            tax_rate=base.tax_rate,
            reinvestment_rate=base.reinvestment_rate,
            terminal_growth=Decimal(str(round(term, 6))),
            equity_risk_premium=base.equity_risk_premium,
            risk_premium_adjustment=base.risk_premium_adjustment,
        )
        try:
            r = run_dcf(f, risk_free_rate=risk_free_rate, assumptions=a)
        except Exception:
            continue
        prices.append(float(r.implied_share_price))

    if not prices:
        return MonteCarloResult(
            iterations=0,
            mean_price=Decimal(0),
            std_price=Decimal(0),
            p10=Decimal(0),
            p50=Decimal(0),
            p90=Decimal(0),
        )
    qs = quantiles(prices, n=10)
    p10, p50, p90 = qs[0], qs[4], qs[8]
    return MonteCarloResult(
        iterations=len(prices),
        mean_price=Decimal(str(round(mean(prices), 4))),
        std_price=Decimal(str(round(stdev(prices) if len(prices) > 1 else 0, 4))),
        p10=Decimal(str(round(p10, 4))),
        p50=Decimal(str(round(p50, 4))),
        p90=Decimal(str(round(p90, 4))),
    )
