from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Date, DateTime, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db import Base


class TickerRow(Base):
    __tablename__ = "tickers"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(256))
    sector: Mapped[str | None] = mapped_column(String(64), index=True)
    industry: Mapped[str | None] = mapped_column(String(128))
    universe: Mapped[str] = mapped_column(String(16), index=True, default="SP500")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FundamentalsSnapshot(Base):
    __tablename__ = "fundamentals_snapshot"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    sector: Mapped[str | None] = mapped_column(String(64), index=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    market_cap: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    beta: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    pe_ratio: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    ev_ebitda: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    fcf_yield: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    revenue_cagr_3y: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    roic: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    debt_to_equity: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


Index("idx_snap_sector_as_of", FundamentalsSnapshot.sector, FundamentalsSnapshot.as_of)
