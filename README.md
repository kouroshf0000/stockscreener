# AlphaArchitect Terminal

Automated equity research + DCF valuation engine with an autonomous stock-hunting agent. Retail-trader grade, free-tier infra, ~$4/month runtime cost.

Built to the analytical standards of an HBS/Wharton-trained equity research analyst: Porter / unit-economics framing, first-principles DCF, disconfirming-evidence mindset. Never issues a buy/sell recommendation — produces analysis.

## Architecture

```
                        ┌─────────────────────────────────────┐
                        │  Next.js 15 frontend (/, /screen,   │
                        │  /ticker/[sym], /hunter)            │
                        └──────────────┬──────────────────────┘
                                       │  REST /api/v1
                        ┌──────────────┴──────────────────────┐
                        │  FastAPI app (+ CORS, rate limit)   │
                        └─┬──────┬──────┬──────┬──────┬───────┘
           /screen        │      │      │      │      │
           /valuate  ─────┤      │      │      │      │
           /comps    ─────┼──────┤      │      │      │
           /risk     ─────┼──────┼──────┤      │      │
           /export/*─────┼──────┼──────┼──────┤      │
           /hunt    ─────┴──────┴──────┴──────┴──────┘
                        │
           ┌────────────┼────────────┬────────────┬──────────────┐
           │            │            │            │              │
     Screener      Valuation      Comps         NLP          Hunter
     (DSL, ETF)   (DCF, WACC,    (peer map,   (Haiku 4.5,   (scouts,
                   sensitivity,   weighted    persona,       conviction
                   Monte Carlo,   multiples)   10-K risk)    gate,
                   auditor)                                  narrative)
           │            │            │            │              │
           └─────┬──────┴──────┬─────┴────────────┴──────────────┘
                 │             │
          Redis cache    yfinance + SEC EDGAR + FRED
           (24h/15m/5m)
                 │
        ┌────────┴─────────┐
        │  arq worker      │  nightly cron @ 06:00 UTC → run_hunt
        │  Postgres        │  snapshots, ledger
        └──────────────────┘
```

## Quickstart

```bash
cp .env.example .env           # fill in ANTHROPIC_API_KEY, FRED_API_KEY (optional)
docker compose up -d           # postgres + redis
uv sync                        # install python deps into .venv
make api                       # FastAPI on :8000
make worker                    # arq worker + nightly 06:00 UTC hunt
make web-install && make web   # Next.js on :3000
make test                      # 37 tests, 84% coverage
```

## API

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v1/fundamentals/{ticker}` | GET | Normalized yfinance data |
| `/api/v1/quote/{ticker}` | GET | Live-ish price + volume |
| `/api/v1/risk-free-rate` | GET | 10Y Treasury (FRED, cached) |
| `/api/v1/screen` | POST | Relational filters across S&P 500 / NDX |
| `/api/v1/valuate/{ticker}` | POST | Full DCF + sensitivity + audit |
| `/api/v1/comps/{ticker}` | GET | Peer-weighted multiples + implied price |
| `/api/v1/risk/{ticker}` | GET | Haiku-scored 10-K risk factors |
| `/api/v1/export/xlsx/{ticker}` | GET | Locked formula workbook |
| `/api/v1/export/pdf/{ticker}` | GET | Investment memo with analyst-voice thesis |
| `/api/v1/hunt` | POST | Run autonomous discovery hunt |
| `/api/v1/hunt/history` | GET | Track record ledger |

## Cost model

| Component | Cost/month |
|---|---|
| Postgres, Redis, yfinance, EDGAR, FRED | $0 |
| Haiku 4.5 (risk scoring, ~15K in / 500 out, cached) | ~$0.54 |
| Haiku 4.5 (thesis narrative, ~2K in / 700 out, cached) | ~$0.18 |
| Hunter @ 5 tickers × 30 days | ~$3.60 |
| **Total** | **~$4** |

Flip `NARRATIVE_MODEL=claude-sonnet-4-6` in `.env` for premium narrative voice (~$10/mo instead).

## Configuration surfaces

- **Model choice:** `HAIKU_MODEL`, `SONNET_MODEL`, `NARRATIVE_MODEL`, `RISK_MODEL` in `.env`.
- **Cache TTLs:** `CACHE_TTL_FUNDAMENTALS_S` (24h), `CACHE_TTL_QUOTES_S` (15m), `CACHE_TTL_HAIKU_S` (5m).
- **Hunter cadence:** `backend/workers/settings.py` cron (`hour=6, minute=0`).
- **Conviction gate thresholds:** `backend/hunter/gate.py` (`MIN_UPSIDE`, `MAX_COMPS_DIVERGENCE`, `MIN_MARKET_CAP`).
- **Scout weights:** `backend/hunter/engine.py::SCOUT_WEIGHTS`.
- **Analyst persona:** `backend/nlp/persona.py` — swap for a different voice.

## Layout

```
backend/
  app/          FastAPI + CORS + rate limit + routes
  data_providers/  yfinance, EDGAR, FRED clients (Redis cached)
  screener/     DSL engine, sector medians, ETF overlap
  valuation/    DCF, WACC, sensitivity, Monte Carlo, auditor
  comps/        peer map + weighted multiples
  nlp/          Haiku risk scorer, thesis narrative, persona
  exports/      XLSX (locked formulas) + PDF memo
  hunter/       scouts, conviction gate, ledger
  workers/      arq worker + nightly cron
  migrations/   alembic (async)
  tests/        37 tests, 84% coverage
frontend/       Next.js 15 + Tailwind (/, /screen, /ticker, /hunter)
```

See [PLAN.md](PLAN.md) for the full phase breakdown.
