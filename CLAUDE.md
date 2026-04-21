# AlphaArchitect Terminal — Claude Code Rules

## Context window discipline (highest priority)

- **Never `cat` a whole file.** Use `Read` with `offset`/`limit`, or `Grep` for targeted searches. Only read what you need to answer the question.
- **Never `grep -r` the whole repo via Bash.** Use the `Grep` tool with a scoped `path` and `glob`.
- **Cap subagent return summaries at 150 words.** Pass `model: haiku` for mechanical tasks (search, rename, bulk edits); `sonnet` for reasoning; `opus` only when explicitly requested.
- **Delete plan files when the work is done.** Stale plan files load every turn.
- **Run `/compact` after large feature landings** before starting the next task.

## Project layout (don't re-explore this each session)

```
backend/
  app/           # FastAPI app, routes, config, supabase_client
  trading/       # alpaca_trader, signal_generator, loss_analyzer
  pipeline/      # run.py — GitHub Actions entry point
  nlp/           # equity_researcher (Claude calls: DCF + trade signal)
  filings/       # thirteenf, conviction_screener
  technicals/    # tv_enrichment, engine
  valuation/     # DCF engine, comps
  backtester/    # backtest engine + models
  exports/       # pdf_memo, xlsx_writer
frontend/
  app/           # Next.js App Router pages
vercel.json      # rewrites /api/* → Render backend
render.yaml      # Render build/start config
```

## Stack

- **Backend:** Python 3.12, FastAPI, uv, alpaca-py, yfinance, supabase-py, anthropic SDK
- **Frontend:** Next.js 14 App Router, TypeScript, Tailwind CSS
- **DB:** Supabase (HTTP via supabase-py — never direct PostgreSQL, IPv4 pooler is broken on free tier)
- **Cache:** Redis optional — `get_redis()` returns `None` when `REDIS_URL` is unset; all callers must guard with `if redis is not None`
- **CI:** GitHub Actions cron `35 13 * * 1-5` (9:35 AM ET weekdays)
- **Hosting:** Render (backend) + Vercel (frontend)

## Claude API usage

- Default model: `claude-opus-4-7` with `thinking: {"type": "adaptive"}`
- All Claude calls live in `backend/nlp/equity_researcher.py` — add new ones there, not scattered across modules
- Use `client.messages.parse(output_format=MyPydanticModel)` for structured outputs — never manually parse JSON from Claude responses
- System prompt uses `cache_control: {"type": "ephemeral"}` — keep it stable across calls

## Trading pipeline rules

- Entry orders use `submit_bracket_order()` — never plain `submit_notional_order()` for new positions
- Bracket fallback to plain market is built-in; don't add extra fallback layers
- Supabase writes in pipeline/routes are fire-and-forget — always wrapped in `try/except`, never block order flow
- `_POSITION_SIZE_USD = Decimal("1000")` is the flat notional per position — change it in `signal_generator.py` only
- Dry-run mode skips orders AND loss analysis — keep it that way for CI testing

## Code style

- No comments explaining what code does — only comments for non-obvious WHY
- No docstrings on internal functions
- Pydantic models use `model_config = ConfigDict(frozen=True)` by default
- Async DB and Alpaca calls use `asyncio.to_thread()` for sync SDK calls
- Never add error handling for scenarios that can't happen — trust framework guarantees

## What NOT to do

- Don't add `greenlet` or SQLAlchemy async again — we use supabase-py HTTP, not SQLAlchemy
- Don't connect to Supabase via direct PostgreSQL/asyncpg — IPv4 pooler fails on free tier
- Don't skip Redis guards — `get_redis()` can return `None` and callers must handle it
- Don't read `graphify-out/GRAPH_REPORT.md` in full — grep it or read top 50 lines only
