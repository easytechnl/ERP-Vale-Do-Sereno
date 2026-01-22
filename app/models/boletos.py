from sqlalchemy import String, Integer, ForeignKey, Numeric, DateTime, Text, Date
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON
from app.models.base import Base
from datetime import datetime

class Boleto(Base):
    __tablename__ = "boletos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    installment_id: Mapped[int] = mapped_column(ForeignKey("installments.id"), unique=True, index=True)
    nosso_numero: Mapped[str] = mapped_column(String(50), index=True)
    digitable_line: Mapped[str] = mapped_column(String(200))
    barcode: Mapped[str] = mapped_column(String(200))
    due_date: Mapped["Date"] = mapped_column(Date, index=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="EMITIDA")
    pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    installment = relationship("Installment")

class CnabRemittance(Base):
    __tablename__ = "cnab_remittances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competence_month: Mapped[str] = mapped_column(String(7), index=True)
    status: Mapped[str] = mapped_column(String(30), default="GERADA")
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class CnabReturnImport(Base):
    __tablename__ = "cnab_return_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competence_month: Mapped[str] = mapped_column(String(7), index=True)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    summary_json: Mapped[dict | None] = mapped_column(SQLITE_JSON, nullable=True)

class CnabEvent(Base):
    __tablename__ = "cnab_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    return_import_id: Mapped[int] = mapped_column(ForeignKey("cnab_return_imports.id"), index=True)
    boleto_id: Mapped[int | None] = mapped_column(ForeignKey("boletos.id"), nullable=True, index=True)
    occurrence_code: Mapped[str] = mapped_column(String(20))
    occurrence_desc: Mapped[str] = mapped_column(String(255))
    paid_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    paid_at: Mapped["Date | None"] = mapped_column(Date, nullable=True)
    raw_line: Mapped[str | None] = mapped_column(Text, nullable=True)

    boleto = relationship("Boleto")
