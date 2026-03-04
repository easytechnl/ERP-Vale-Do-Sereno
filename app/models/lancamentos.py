from datetime import datetime

from sqlalchemy import String, Integer, ForeignKey, Numeric, Date, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class LedgerEntry(Base):
    """Lançamento financeiro (entrada/saída) para saldos e relatórios.

    - kind: ENTRADA ou SAIDA
    - status: PREVISTO ou REALIZADO (saldo/relatórios consideram REALIZADO por padrão)
    """

    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    competence_month: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    entry_date: Mapped["Date"] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(10), index=True)  # ENTRADA/SAIDA
    status: Mapped[str] = mapped_column(String(12), index=True, default="REALIZADO")  # PREVISTO/REALIZADO

    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    document_number: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    cost_center: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)

    bank_account_id: Mapped[int | None] = mapped_column(ForeignKey("bank_accounts.id"), index=True, nullable=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    bank_account = relationship("BankAccount")
    customer = relationship("Customer")
