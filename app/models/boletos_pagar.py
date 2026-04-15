from __future__ import annotations

from datetime import datetime, date

from sqlalchemy import String, Integer, Numeric, Date, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BoletoAPagar(Base):
    """Boletos (contas a pagar) cadastrados manualmente.

    Status sugeridos:
      - PAGO
      - A_VENCER
      - VENCIDO
    """

    __tablename__ = "boletos_a_pagar"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    competence_month: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM

    beneficiario: Mapped[str] = mapped_column(String(180), index=True)
    descricao: Mapped[str | None] = mapped_column(String(255), nullable=True)
    numero_nota_fiscal: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)

    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)

    status: Mapped[str] = mapped_column(String(30), default="A_VENCER", index=True)
    paid_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    barcode: Mapped[str | None] = mapped_column(Text, nullable=True)
    digitable_line: Mapped[str | None] = mapped_column(Text, nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
