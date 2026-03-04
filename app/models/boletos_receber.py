from __future__ import annotations

import datetime as dt

from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.models.base import Base


class BoletoAReceber(Base):
    """Boletos a receber cadastrados manualmente."""

    __tablename__ = "boletos_a_receber"

    id = Column(Integer, primary_key=True, index=True)

    # Competência no formato YYYY-MM
    competence_month = Column(String(7), index=True, nullable=False)

    # Dados do sacado (cliente)
    customer_name = Column(String(120), nullable=False)
    customer_email = Column(String(120), nullable=True)

    description = Column(String(200), nullable=True)
    due_date = Column(Date, nullable=True)

    amount = Column(Float, nullable=False, default=0.0)

    # Vinculo opcional com Nota Fiscal cadastrada
    nota_fiscal_id = Column(Integer, ForeignKey("notas_fiscais.id"), nullable=True, index=True)
    nota_fiscal = relationship("NotaFiscal")

    # A_VENCER | VENCIDO | PAGO
    status = Column(String(20), nullable=False, default="A_VENCER")

    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=dt.datetime.utcnow)
