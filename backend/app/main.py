from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from backend.app.config import get_settings
from backend.app.logging import configure_logging

limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
from backend.app.routes.backtest import router as backtest_router
from backend.app.routes.comps import router as comps_router
from backend.app.routes.exports import router as exports_router
from backend.app.routes.filings import router as filings_router
from backend.app.routes.fundamentals import router as fundamentals_router
from backend.app.routes.hunter import router as hunter_router
from backend.app.routes.news import router as news_router
from backend.app.routes.technicals import router as technicals_router
from backend.app.routes.paper_trade import router as paper_trade_router
from backend.app.routes.researcher import router as researcher_router
from backend.app.routes.risk import router as risk_router
from backend.app.routes.screen import router as screen_router
from backend.app.routes.valuation import router as valuation_router

configure_logging()

app = FastAPI(title="AlphaArchitect Terminal", version="0.1.0")
app.state.limiter = limiter
_cors_origins = ["http://localhost:3000", "https://localhost:3000"]
if get_settings().cors_origins:
    _cors_origins.extend(o.strip() for o in get_settings().cors_origins.split(",") if o.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RateLimitExceeded)
async def _rate_limited(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(status_code=429, content={"detail": f"rate limit: {exc.detail}"})


@app.exception_handler(Exception)
async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
    origin = _request.headers.get("origin", "")
    headers = {}
    if origin:
        headers["access-control-allow-origin"] = origin
        headers["access-control-allow-credentials"] = "true"
    return JSONResponse(status_code=500, content={"detail": str(exc)}, headers=headers)
app.include_router(backtest_router)
app.include_router(fundamentals_router)
app.include_router(screen_router)
app.include_router(valuation_router)
app.include_router(comps_router)
app.include_router(risk_router)
app.include_router(exports_router)
app.include_router(hunter_router)
app.include_router(technicals_router)
app.include_router(news_router)
app.include_router(filings_router)
app.include_router(researcher_router)
app.include_router(paper_trade_router)


@app.get("/")
async def root() -> dict[str, object]:
    return {
        "service": "AlphaArchitect Terminal",
        "version": "0.1.0",
        "frontend": "http://localhost:3000",
        "docs": "http://localhost:8000/docs",
        "endpoints": [
            "/health",
            "/api/v1/fundamentals/{ticker}",
            "/api/v1/quote/{ticker}",
            "/api/v1/risk-free-rate",
            "/api/v1/screen (POST)",
            "/api/v1/valuate/{ticker} (POST)",
            "/api/v1/comps/{ticker}",
            "/api/v1/risk/{ticker}",
            "/api/v1/technicals/{ticker}",
            "/api/v1/news/{ticker}",
            "/api/v1/hunt (POST)",
            "/api/v1/hunt/history",
            "/api/v1/export/xlsx/{ticker}",
            "/api/v1/export/pdf/{ticker}",
        ],
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "env": get_settings().env}
