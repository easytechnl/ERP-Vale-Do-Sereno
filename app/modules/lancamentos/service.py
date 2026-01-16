from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.models.lancamentos import LedgerEntry


def month_range(start_ym: str, end_ym: str) -> list[str]:
    """Retorna lista de meses (YYYY-MM) inclusive."""
    sy, sm = [int(x) for x in start_ym.split("-")]
    ey, em = [int(x) for x in end_ym.split("-")]
    out: list[str] = []
    y, m = sy, sm
    while (y < ey) or (y == ey and m <= em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


def list_entries(
    db: Session,
    competence: Optional[str] = None,
    kind: Optional[str] = None,
    status: Optional[str] = None,
    bank_account_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    q: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 500,
) -> list[LedgerEntry]:
    qry = db.query(LedgerEntry)

    conds = []
    if competence:
        conds.append(LedgerEntry.competence_month == competence)
    if kind:
        conds.append(LedgerEntry.kind == kind)
    if status:
        conds.append(LedgerEntry.status == status)
    if bank_account_id:
        conds.append(LedgerEntry.bank_account_id == bank_account_id)
    if customer_id:
        conds.append(LedgerEntry.customer_id == customer_id)
    if date_from:
        conds.append(LedgerEntry.entry_date >= date_from)
    if date_to:
        conds.append(LedgerEntry.entry_date <= date_to)
    if q:
        like = f"%{q.strip()}%"
        conds.append(
            (LedgerEntry.description.ilike(like))
            | (LedgerEntry.category.ilike(like))
            | (LedgerEntry.cost_center.ilike(like))
        )

    if conds:
        qry = qry.filter(and_(*conds))

    return qry.order_by(LedgerEntry.entry_date.desc(), LedgerEntry.id.desc()).limit(limit).all()


def create_entry(
    db: Session,
    *,
    competence: str,
    entry_date: date,
    kind: str,
    amount: float,
    description: str,
    status: str = "REALIZADO",
    category: Optional[str] = None,
    cost_center: Optional[str] = None,
    bank_account_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> LedgerEntry:
    ent = LedgerEntry(
        competence_month=competence,
        entry_date=entry_date,
        kind=kind,
        status=status,
        amount=float(amount),
        description=description,
        category=category,
        cost_center=cost_center,
        bank_account_id=bank_account_id,
        customer_id=customer_id,
        notes=notes,
    )
    db.add(ent)
    db.commit()
    db.refresh(ent)
    return ent


def delete_entry(db: Session, entry_id: int) -> bool:
    ent = db.get(LedgerEntry, entry_id)
    if not ent:
        return False
    db.delete(ent)
    db.commit()
    return True


def totals_for_period(
    db: Session,
    *,
    start_ym: str,
    end_ym: str,
    bank_account_id: Optional[int] = None,
    status: str = "REALIZADO",
) -> dict:
    months = month_range(start_ym, end_ym)

    conds = [LedgerEntry.competence_month.in_(months), LedgerEntry.status == status]
    if bank_account_id:
        conds.append(LedgerEntry.bank_account_id == bank_account_id)

    base = db.query(LedgerEntry).filter(and_(*conds)).subquery()

    entradas = db.query(func.coalesce(func.sum(base.c.amount), 0.0)).filter(base.c.kind == "ENTRADA").scalar()  # type: ignore
    saidas = db.query(func.coalesce(func.sum(base.c.amount), 0.0)).filter(base.c.kind == "SAIDA").scalar()  # type: ignore
    entradas_f = float(entradas or 0.0)
    saidas_f = float(saidas or 0.0)
    return {"entradas": entradas_f, "saidas": saidas_f, "saldo": entradas_f - saidas_f, "months": months}


def series_by_month(
    db: Session,
    *,
    start_ym: str,
    end_ym: str,
    bank_account_id: Optional[int] = None,
    status: str = "REALIZADO",
) -> list[dict]:
    months = month_range(start_ym, end_ym)
    out: list[dict] = []
    for ym in months:
        conds = [LedgerEntry.competence_month == ym, LedgerEntry.status == status]
        if bank_account_id:
            conds.append(LedgerEntry.bank_account_id == bank_account_id)
        entradas = (
            db.query(func.coalesce(func.sum(LedgerEntry.amount), 0.0))
            .filter(and_(*conds), LedgerEntry.kind == "ENTRADA")
            .scalar()
        )
        saidas = (
            db.query(func.coalesce(func.sum(LedgerEntry.amount), 0.0))
            .filter(and_(*conds), LedgerEntry.kind == "SAIDA")
            .scalar()
        )
        e = float(entradas or 0.0)
        s = float(saidas or 0.0)
        out.append({"competence": ym, "entradas": e, "saidas": s, "saldo": e - s})
    return out
