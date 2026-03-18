from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class InvestmentAccount(Base):
    __tablename__ = "investment_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    institution: Mapped[str | None] = mapped_column(String(120), nullable=True)
    account_number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    opening_balance: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    opening_date: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    entries: Mapped[list["InvestmentEntry"]] = relationship(
        "InvestmentEntry",
        back_populates="account",
        cascade="all, delete-orphan",
    )


class InvestmentEntry(Base):
    __tablename__ = "investment_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    investment_account_id: Mapped[int] = mapped_column(
        ForeignKey("investment_accounts.id"),
        index=True,
        nullable=False,
    )
    competence_month: Mapped[str] = mapped_column(String(7), index=True)
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    reference_month: Mapped[str | None] = mapped_column(String(7), index=True, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    account: Mapped[InvestmentAccount] = relationship("InvestmentAccount", back_populates="entries")
