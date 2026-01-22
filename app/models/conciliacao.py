from sqlalchemy import String, Integer, ForeignKey, Numeric, DateTime, Text, Date
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON
from app.models.base import Base
from datetime import datetime

class BankStatementImport(Base):
    __tablename__ = "bank_statement_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competence_month: Mapped[str] = mapped_column(String(7), index=True)
    source_type: Mapped[str] = mapped_column(String(20), default="OFX")  # OFX/CSV
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class BankTransaction(Base):
    __tablename__ = "bank_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("bank_statement_imports.id"), index=True)
    txn_date: Mapped["Date"] = mapped_column(Date, index=True)
    description: Mapped[str] = mapped_column(String(255))
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    kind: Mapped[str] = mapped_column(String(10))  # credit/debit
    fit_id: Mapped[str] = mapped_column(String(128), index=True)
    raw_json: Mapped[dict | None] = mapped_column(SQLITE_JSON, nullable=True)

    statement_import = relationship("BankStatementImport")

class Reconciliation(Base):
    __tablename__ = "reconciliations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bank_transaction_id: Mapped[int] = mapped_column(ForeignKey("bank_transactions.id"), unique=True, index=True)
    matched_type: Mapped[str] = mapped_column(String(30))  # installment/payable/manual
    matched_id: Mapped[int] = mapped_column(Integer)  # id do alvo
    status: Mapped[str] = mapped_column(String(30), default="CONFIRMADA")
    confidence: Mapped[int] = mapped_column(Integer, default=100)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reconciled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    bank_transaction = relationship("BankTransaction")
