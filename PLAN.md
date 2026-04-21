# AlphaArchitect Terminal — Implementation Plan

**Goal:** Free-tier equity research + DCF valuation engine. Retail-trader grade.
**Budget:** ~$1/month (Haiku API only). Everything else $0.

---

## Stack (locked)

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Decimal precision, async native |
| API | FastAPI | Async, OpenAPI docs free |
| Queue | `arq` | Redis-backed, async, ~400 LOC — not Celery |
| Cache/Queue broker | Redis (local Docker) | Free |
| DB | Postgres (local Docker) | Free |
| Fundamentals | `yfinance` + SEC EDGAR | Free, unlimited |
| Risk-free rate | FRED API | Free with key |
| Runtime NLP | Claude Haiku 4.5 via Anthropic SDK | ~$0.02/ticker |
| Excel | `XlsxWriter` | Free, cell-locking supported |
| PDF memo | `reportlab` or `weasyprint` | Free |
| Frontend | Next.js + shadcn/ui | Free, one app |

---

## Phase 0 — Scaffolding (½ day)

- [ ] `docker-compose.yml`: Postgres + Redis
- [ ] Poetry/uv project: `backend/`, `frontend/`, `workers/`
- [ ] `.env.example`: `ANTHROPIC_API_KEY`, `FRED_API_KEY`, DB/Redis URLs
- [ ] Alembic migrations skeleton
- [ ] `ruff` + `mypy` + `pytest` configured
- [ ] CI: GitHub Actions free tier (lint + test on PR)

## Phase 1 — Data Ingestion Layer (2 days)

**Module:** `backend/data_providers/`

- [ ] `yfinance_client.py` — wrapper with retry + Redis cache (24h TTL for fundamentals, 15min for quotes)
- [ ] `edgar_client.py` — SEC EDGAR XBRL fetch for 10-K/10-Q (fallback + normalization source)
- [ ] `fred_client.py` — risk-free rate (10Y Treasury, `DGS10`)
- [ ] **Idempotency:** Redis key `ticker:{SYMBOL}:fundamentals:{YYYYMMDD}` → skip re-fetch
- [ ] Unit tests with `vcrpy` to record real API responses once, replay in CI

**Acceptance:** `GET /api/v1/fundamentals/NVDA` returns normalized JSON in <500ms cached, <3s cold.

## Phase 2 — Screener (Module A) (2 days)

**Module:** `backend/screener/`

- [ ] Postgres schema: `tickers`, `fundamentals_snapshot`, `sector_aggregates` (nightly materialized view)
- [ ] Nightly `arq` job: refresh S&P 500 + Nasdaq 100 fundamentals
- [ ] Relational filter DSL: `{"pe_vs_sector": "<0.8", "revenue_cagr_3y": ">0.15"}`
- [ ] ETF overlap: hardcode top-10 holdings for ARKK/XLK/SPY/QQQ (scrape weekly from issuer sites — free)
- [ ] `POST /api/v1/screen` → returns ≤50 finalists

**Acceptance:** "P/E 20% below sector AND 3Y revenue CAGR > 15%" returns a reproducible list.

## Phase 3 — Valuation Engine (Module B) (4 days) ⭐ core

**Module:** `backend/valuation/`

- [ ] `normalization.py` — strip non-recurring items from Cash Flow (legal settlements, asset sales) using keyword matching on line-item names
- [ ] `wacc.py`:
  - Cost of Equity = CAPM via FRED R_f, beta from yfinance, ERP = 5.5% (hardcoded default, overrideable)
  - Cost of Debt = weighted-avg interest expense / total debt
- [ ] `dcf.py` — 5-year explicit + terminal (Gordon Growth). **All math in `Decimal`**, never float
- [ ] `sensitivity.py` — 2D table: terminal growth [1%–3% step 0.5%] × WACC [7%–11% step 0.5%] = 45 scenarios
- [ ] `monte_carlo.py` — optional, 10K iterations with normal distributions around base assumptions
- [ ] **Auditor loop:** compare Total Debt (API) vs Balance Sheet Debt; abort export if delta >0.5%
- [ ] **Red-flag rule:** FCF growth > Revenue growth for 3+ consecutive years → thesis warning
- [ ] Dispatch as `arq` task — returns job_id, poll `GET /api/v1/jobs/{id}`

**Acceptance:** NVDA valuation completes <20s; sensitivity table matches manual spot-check to 2 decimals.

## Phase 4 — Comps / Relative Valuation (Module C) (1.5 days)

- [ ] Peer map: yfinance sector + curated overrides JSON for top 200 tickers
- [ ] Weighted Peer Multiple = Σ(peer_market_cap × peer_multiple) / Σ(peer_market_cap)
- [ ] Implied price from median EV/EBITDA and P/E
- [ ] Merge into valuation output as "Comps Cross-Check" section

## Phase 5 — Claude Haiku Risk Analysis (1 day)

**Module:** `backend/nlp/`

- [ ] Fetch 10-K "Item 1A. Risk Factors" from EDGAR
- [ ] Chunk + send to Haiku with structured output schema: `{legal_risk: 0-3, regulatory_risk: 0-3, macro_risk: 0-3, summary: str}`
- [ ] Map to discount-rate adjustment: each "3" → +0.33% risk premium (cap total at +2%)
- [ ] **Prompt caching enabled** (system prompt + 10-K body cached 5min, saves 90% on re-runs)
- [ ] Log prompt + response to `ai_audit_log` table for reproducibility

**Acceptance:** Same 10-K → same scores (deterministic with `temperature=0`). Cost per ticker logged.

## Phase 6 — Exports (2 days)

- [ ] `xlsx_writer.py`:
  - Tabs: Summary, Assumptions (editable), DCF, Comps, Sensitivity, Red Flags
  - Assumptions tab UNLOCKED; formula tabs LOCKED with password
  - Named ranges so user edits to WACC propagate live
- [ ] `pdf_memo.py` — Investment Memorandum template with valuation bridge chart (matplotlib)

## Phase 7 — Frontend Dashboard (3 days)

- [ ] Next.js App Router + shadcn/ui
- [ ] Pages: `/screen`, `/ticker/[symbol]`, `/jobs/[id]`
- [ ] Valuation Bridge chart: waterfall current price → target (Recharts, free)
- [ ] Job polling with SWR; skeleton loaders during DCF run
- [ ] Download buttons for XLSX + PDF

## Phase 8 — Autonomous Discovery Agent (3 days) ⭐ the "hunter"

**Module:** `backend/hunter/`

The system proactively scans the universe on a schedule, picks high-conviction names, runs the full valuation pipeline on each, and files a defended investment case — no user input required.

### 8.1 Multi-strategy scanner (nightly, 2am ET)
Runs four independent "scouts" in parallel over the S&P 500 + Nasdaq 100 universe. Each scout outputs a ranked list with a score 0–100:

| Scout | Thesis | Signals |
|---|---|---|
| **Value** | Mispriced vs fundamentals | P/E < sector × 0.8, FCF yield > 5%, EV/EBITDA < 5Y avg |
| **Quality-Compounder** | Durable growth | ROIC > 15% for 5Y, Revenue CAGR > 10%, Debt/Equity < 1 |
| **Momentum-with-Earnings** | Trend + fundamentals | Price > 200DMA, EPS revisions up, RS rank > 80 |
| **Catalyst** | Event-driven | Insider buys, upcoming earnings, 52W-low bounce, 10-K risk score *dropping* vs prior year |

### 8.2 Composite ranker
- Each ticker gets 4 scout scores → combined via weighted average (defaults: 30/30/20/20, configurable)
- Top **10 candidates** promoted to "watchlist"
- Top **5 candidates** auto-run through the full Phase 3 valuation + Phase 4 comps + Phase 5 Haiku risk pipeline

### 8.3 Conviction gate (the "defense" threshold)
A pick is only published if it clears ALL of:
- [ ] DCF implied upside > 20% vs current price
- [ ] Comps implied price agrees within ±25% of DCF (cross-validation)
- [ ] Auditor loop passes (debt reconciliation)
- [ ] No unresolved red flags from Haiku (legal_risk < 3)
- [ ] Liquidity check: avg daily volume > $10M

Picks that fail gate → logged to `rejected_picks` table with the failing rule. (Transparency > recall.)

### 8.4 Auto-generated deliverables per pick
For each pick that clears the gate:
- [ ] Dashboard card on `/hunter` page with valuation bridge, scout scores, thesis bullets
- [ ] Full XLSX model (Phase 6 output)
- [ ] PDF memo with a new top section: **"Why the System Picked This"** — lists which scouts fired, composite score, conviction-gate pass/fail ledger, and a 3-bullet plain-English thesis generated by Haiku from the quant signals

### 8.5 Track record ledger
- [ ] `hunter_picks` table: ticker, pick_date, pick_price, target_price, scout_scores, composite_score, deliverables_urls
- [ ] Daily `arq` job marks-to-market every open pick → stores cumulative return
- [ ] Dashboard tab `/hunter/performance`: win rate, avg return, Sharpe, vs SPY benchmark
- [ ] **Honesty clause:** losses and rejected picks shown equally prominently — the system defends its *process*, not its ego

### 8.6 Explainability layer
Every pick must answer three questions in the memo, generated from the pipeline's own state (no LLM invention):
1. **"Why now?"** → which scout triggered and what signal changed vs last scan
2. **"What has to be true?"** → the 3 key assumptions driving the DCF (growth, margin, terminal rate)
3. **"What would kill this thesis?"** → the top 2 red flags and the sensitivity-table scenario that breaks the upside

**Acceptance:**
- Cron runs nightly; next morning `/hunter` shows 0–5 new picks with full deliverables linked.
- Each pick has a reproducible scout-score audit trail.
- Rejected picks are visible with reasons.
- Performance ledger updates daily and can be compared to SPY.

---

## Phase 9 — Hardening (1 day)

- [ ] Rate-limit middleware (per-IP, `slowapi`)
- [ ] Structured logging (`structlog` → JSON)
- [ ] Sentry free tier for error tracking
- [ ] README with architecture diagram + setup

---

## Data flow (runtime)

```
User → /screen → Postgres (nightly snapshot) → 5 finalists
     → /valuate/{ticker} → arq queue → worker:
           ├─ yfinance (cached 24h)
           ├─ EDGAR 10-K fetch
           ├─ FRED r_f
           ├─ Haiku risk scoring (cached 5min)
           ├─ Normalize → WACC → DCF → Sensitivity
           ├─ Auditor check (abort if debt mismatch)
           └─ Write XLSX + PDF to /exports
     → Frontend polls job → download
```

---

## Risk register

| Risk | Mitigation |
|---|---|
| yfinance scrape breaks | EDGAR fallback in Phase 1 |
| Rate limits on Yahoo | 24h Redis cache + nightly batch |
| Haiku hallucinates risk scores | Structured output + audit log + deterministic temp=0 |
| Floating-point drift in DCF | `Decimal` enforced via `mypy` strict + unit tests |
| API key leakage | `.env` + pre-commit `detect-secrets` |

---

## Timeline

~**19 working days** solo. Milestones:
- **Day 5:** Screener + data layer demoable
- **Day 10:** DCF engine producing XLSX for one ticker
- **Day 14:** Full frontend + comps + Haiku integration
- **Day 18:** Autonomous Hunter running nightly, filing defended picks
- **Day 19:** Hardened, documented, deployed locally

---

## Next step

Approve this plan → I scaffold Phase 0 (docker-compose + project layout) in one pass.
