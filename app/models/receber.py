from sqlalchemy import String, Integer, Boolean, ForeignKey, Numeric, Date, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

class Receivable(Base):
    __tablename__ = "receivables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    customer = relationship("Customer")

class Installment(Base):
    __tablename__ = "installments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receivable_id: Mapped[int] = mapped_column(ForeignKey("receivables.id"), index=True)
    competence_month: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    due_date: Mapped["Date"] = mapped_column(Date, index=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="GERADA")  # GERADA/EMITIDA/ENVIADA/VENCIDA/PAGA/BAIXADA/CANCELADA
    paid_at: Mapped["Date | None"] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    receivable = relationship("Receivable")
