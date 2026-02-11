from __future__ import annotations

from datetime import datetime, date

from sqlalchemy import String, Integer, Numeric, Date, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class NotaFiscal(Base):
    """Notas fiscais (contas a pagar).

    O status é mantido como string para facilitar filtros e marcação manual.
    Valores suportados (sugeridos):
      - PAGA
      - A_VENCER
      - VENCIDA
    """

    __tablename__ = "notas_fiscais"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    numero: Mapped[str] = mapped_column(String(80), index=True)
    fornecedor: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    descricao: Mapped[str | None] = mapped_column(String(255), nullable=True)

    competence_month: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM

    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)

    status: Mapped[str] = mapped_column(String(30), default="A_VENCER", index=True)
    paid_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
