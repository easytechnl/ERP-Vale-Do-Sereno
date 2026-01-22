from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Integer, Numeric, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BalanceAdjustment(Base):
    """Ajuste manual de saldo por competência (YYYY-MM)."""

    __tablename__ = "balance_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competence_month: Mapped[str] = mapped_column(String(7), index=True)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
