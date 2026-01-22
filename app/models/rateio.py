from __future__ import annotations

from datetime import datetime, date

from sqlalchemy import String, Integer, Numeric, Date, DateTime, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RateioCompany(Base):
    """Construtora/associado que participa do rateio por área/percentual."""

    __tablename__ = "rateio_companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    name: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cnpj: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    # Dados de referência (normalmente vindos da planilha)
    area_m2: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    percentual: Mapped[float | None] = mapped_column(Numeric(14, 10), nullable=True)  # fração (ex: 0.0345)

    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RateioExpense(Base):
    """Despesa inserida manualmente para compor o rateio.

    recurrence_months:
      - 0  => não repete (somente no mês da expense_date)
      - 1  => repete todo mês
      - 2  => repete a cada 2 meses
      - 12 => repete todo ano
    """

    __tablename__ = "rateio_expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    description: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)

    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)

    expense_date: Mapped[date] = mapped_column(Date, index=True)  # data base/primeira ocorrência
    recurrence_months: Mapped[int] = mapped_column(Integer, default=0, index=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
