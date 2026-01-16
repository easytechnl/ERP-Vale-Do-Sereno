from sqlalchemy import String, Integer, DateTime, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON
from app.models.base import Base
from datetime import datetime

class MonthlyClose(Base):
    __tablename__ = "monthly_closes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competence_month: Mapped[str] = mapped_column(String(7), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="ABERTO")  # ABERTO/FECHADO
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lock_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

class ReportSnapshot(Base):
    __tablename__ = "report_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monthly_close_id: Mapped[int] = mapped_column(ForeignKey("monthly_closes.id"), index=True)
    report_type: Mapped[str] = mapped_column(String(50))  # demonstrativo/entradas_saida/inadimplencia
    payload_json: Mapped[dict | None] = mapped_column(SQLITE_JSON, nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
