from datetime import date

from sqlalchemy import String, Integer, Numeric, Date, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BankAccount(Base):
    """Conta bancária para classificar lançamentos e apurar saldo.

    MVP (sem integrações profundas):
    - opening_balance: saldo inicial (no dia opening_date)
    - saldo atual pode ser apurado por somatório de lançamentos (REALIZADO)
    """

    __tablename__ = "bank_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)  # ex: "Conta Principal"
    bank_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    agency: Mapped[str | None] = mapped_column(String(30), nullable=True)
    account_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    opening_balance: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    opening_date: Mapped["Date"] = mapped_column(Date, nullable=False, default=date.today)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
