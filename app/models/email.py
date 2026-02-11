from sqlalchemy import String, Integer, DateTime, Date, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON
from app.models.base import Base
from datetime import datetime

class EmailTemplate(Base):
    __tablename__ = "email_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    subject_tpl: Mapped[str] = mapped_column(String(255))
    body_tpl_html: Mapped[str] = mapped_column(Text)
    variables_json: Mapped[dict | None] = mapped_column(SQLITE_JSON, nullable=True)

class EmailBatch(Base):
    __tablename__ = "email_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competence_month: Mapped[str] = mapped_column(String(7), index=True)
    status: Mapped[str] = mapped_column(String(30), default="CRIADO")  # CRIADO/ENVIANDO/CONCLUIDO/FALHOU
    filters_json: Mapped[dict | None] = mapped_column(SQLITE_JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class EmailMessage(Base):
    __tablename__ = "email_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("email_batches.id"), index=True)
    to_emails: Mapped[str] = mapped_column(Text)  # csv
    subject: Mapped[str] = mapped_column(String(255))
    body_html: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="PENDENTE")  # PENDENTE/ENVIADO/FALHOU
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class EmailAttachment(Base):
    __tablename__ = "email_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email_message_id: Mapped[int] = mapped_column(ForeignKey("email_messages.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # boleto/fechamento/outro
    file_path: Mapped[str] = mapped_column(Text)


class EmailReminderLog(Base):
    __tablename__ = "email_reminder_logs"
    __table_args__ = (
        UniqueConstraint("installment_id", "days_before", name="uq_email_reminder_installment_days"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    installment_id: Mapped[int] = mapped_column(ForeignKey("installments.id"), index=True)
    boleto_id: Mapped[int] = mapped_column(ForeignKey("boletos.id"), index=True)
    customer_email: Mapped[str] = mapped_column(String(255), index=True)
    due_date: Mapped["Date"] = mapped_column(Date)
    days_before: Mapped[int] = mapped_column(Integer, index=True)  # 10, 5, 3, 1
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
