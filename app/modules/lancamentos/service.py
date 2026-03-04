from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import and_, func, inspect, text
from sqlalchemy.orm import Session

from app.models.lancamentos import LedgerEntry
from app.models.lancamento_refs import LedgerCategory, LedgerCostCenter

_LEDGER_SCHEMA_OK = False


def ensure_ledger_entries_schema(db: Session) -> None:
    """Garantir colunas novas em bases antigas sem migração formal."""
    global _LEDGER_SCHEMA_OK
    if _LEDGER_SCHEMA_OK:
        return

    bind = db.get_bind()
    insp = inspect(bind)
    try:
        cols = {c["name"] for c in insp.get_columns("ledger_entries")}
    except Exception:
        return

    changed = False
    if "document_number" not in cols:
        if bind.dialect.name == "sqlite":
            db.execute(text("ALTER TABLE ledger_entries ADD COLUMN document_number VARCHAR(80)"))
        else:
            db.execute(text("ALTER TABLE ledger_entries ADD COLUMN IF NOT EXISTS document_number VARCHAR(80)"))
        changed = True

    if changed:
        try:
            db.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_ledger_entries_document_number "
                    "ON ledger_entries (document_number)"
                )
            )
        except Exception:
            db.rollback()
            return
        db.commit()
    _LEDGER_SCHEMA_OK = True


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
    ensure_ledger_entries_schema(db)
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
            | (LedgerEntry.document_number.ilike(like))
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
    document_number: Optional[str] = None,
    status: str = "REALIZADO",
    category: Optional[str] = None,
    cost_center: Optional[str] = None,
    bank_account_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> LedgerEntry:
    ensure_ledger_entries_schema(db)
    ent = LedgerEntry(
        competence_month=competence,
        entry_date=entry_date,
        kind=kind,
        status=status,
        amount=float(amount),
        description=description,
        document_number=(document_number or None),
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
    ensure_ledger_entries_schema(db)
    ent = db.get(LedgerEntry, entry_id)
    if not ent:
        return False
    db.delete(ent)
    db.commit()
    return True


def _normalize_option_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    value = str(name).strip()
    return value or None


def ensure_lookup_tables(db: Session) -> None:
    bind = db.get_bind()
    LedgerCategory.__table__.create(bind=bind, checkfirst=True)
    LedgerCostCenter.__table__.create(bind=bind, checkfirst=True)


def create_category_option(db: Session, name: str) -> LedgerCategory | None:
    value = _normalize_option_name(name)
    if not value:
        return None
    existing = db.query(LedgerCategory).filter(func.lower(LedgerCategory.name) == value.lower()).first()
    if existing:
        return existing
    item = LedgerCategory(name=value)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def create_cost_center_option(db: Session, name: str) -> LedgerCostCenter | None:
    value = _normalize_option_name(name)
    if not value:
        return None
    existing = db.query(LedgerCostCenter).filter(func.lower(LedgerCostCenter.name) == value.lower()).first()
    if existing:
        return existing
    item = LedgerCostCenter(name=value)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def sync_lookup_options_from_entries(db: Session) -> None:
    ensure_ledger_entries_schema(db)
    cat_values = (
        db.query(func.distinct(LedgerEntry.category))
        .filter(LedgerEntry.category.isnot(None), LedgerEntry.category != "")
        .all()
    )
    for (name,) in cat_values:
        if name:
            create_category_option(db, str(name))

    cc_values = (
        db.query(func.distinct(LedgerEntry.cost_center))
        .filter(LedgerEntry.cost_center.isnot(None), LedgerEntry.cost_center != "")
        .all()
    )
    for (name,) in cc_values:
        if name:
            create_cost_center_option(db, str(name))


def list_category_options(db: Session) -> list[LedgerCategory]:
    return db.query(LedgerCategory).order_by(LedgerCategory.name.asc()).all()


def list_cost_center_options(db: Session) -> list[LedgerCostCenter]:
    return db.query(LedgerCostCenter).order_by(LedgerCostCenter.name.asc()).all()


def rename_category_option(db: Session, option_id: int, new_name: str) -> tuple[LedgerCategory | None, str | None]:
    ensure_ledger_entries_schema(db)
    value = _normalize_option_name(new_name)
    if not value:
        return None, "Nome de categoria inválido."

    item = db.get(LedgerCategory, option_id)
    if not item:
        return None, "Categoria não encontrada."

    existing = (
        db.query(LedgerCategory)
        .filter(func.lower(LedgerCategory.name) == value.lower(), LedgerCategory.id != option_id)
        .first()
    )
    if existing:
        return None, "Já existe uma categoria com esse nome."

    old_name = item.name
    item.name = value
    db.query(LedgerEntry).filter(func.lower(LedgerEntry.category) == old_name.lower()).update(
        {LedgerEntry.category: value},
        synchronize_session=False,
    )
    db.commit()
    db.refresh(item)
    return item, None


def rename_cost_center_option(db: Session, option_id: int, new_name: str) -> tuple[LedgerCostCenter | None, str | None]:
    ensure_ledger_entries_schema(db)
    value = _normalize_option_name(new_name)
    if not value:
        return None, "Nome de centro de custo inválido."

    item = db.get(LedgerCostCenter, option_id)
    if not item:
        return None, "Centro de custo não encontrado."

    existing = (
        db.query(LedgerCostCenter)
        .filter(func.lower(LedgerCostCenter.name) == value.lower(), LedgerCostCenter.id != option_id)
        .first()
    )
    if existing:
        return None, "Já existe um centro de custo com esse nome."

    old_name = item.name
    item.name = value
    db.query(LedgerEntry).filter(func.lower(LedgerEntry.cost_center) == old_name.lower()).update(
        {LedgerEntry.cost_center: value},
        synchronize_session=False,
    )
    db.commit()
    db.refresh(item)
    return item, None


def delete_category_option(db: Session, option_id: int) -> bool:
    item = db.get(LedgerCategory, option_id)
    if not item:
        return False
    db.delete(item)
    db.commit()
    return True


def delete_cost_center_option(db: Session, option_id: int) -> bool:
    item = db.get(LedgerCostCenter, option_id)
    if not item:
        return False
    db.delete(item)
    db.commit()
    return True


def category_usage_map(db: Session) -> dict[str, int]:
    ensure_ledger_entries_schema(db)
    rows = (
        db.query(func.lower(LedgerEntry.category).label("key"), func.count(LedgerEntry.id))
        .filter(LedgerEntry.category.isnot(None), LedgerEntry.category != "")
        .group_by(func.lower(LedgerEntry.category))
        .all()
    )
    return {str(key): int(count) for key, count in rows if key}


def cost_center_usage_map(db: Session) -> dict[str, int]:
    ensure_ledger_entries_schema(db)
    rows = (
        db.query(func.lower(LedgerEntry.cost_center).label("key"), func.count(LedgerEntry.id))
        .filter(LedgerEntry.cost_center.isnot(None), LedgerEntry.cost_center != "")
        .group_by(func.lower(LedgerEntry.cost_center))
        .all()
    )
    return {str(key): int(count) for key, count in rows if key}


def totals_for_period(
    db: Session,
    *,
    start_ym: str,
    end_ym: str,
    bank_account_id: Optional[int] = None,
    status: str = "REALIZADO",
) -> dict:
    ensure_ledger_entries_schema(db)
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
    ensure_ledger_entries_schema(db)
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
