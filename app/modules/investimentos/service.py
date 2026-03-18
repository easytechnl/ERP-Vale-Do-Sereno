from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from app.models.investimentos import InvestmentAccount, InvestmentEntry
from app.modules.lancamentos.service import month_range


ENTRY_KINDS = {"APORTE", "RESGATE", "RENDIMENTO", "AJUSTE"}
REPORT_WINDOWS = {1, 3, 6, 12}


def ensure_investment_schema(db: Session) -> None:
    bind = db.get_bind()
    InvestmentAccount.__table__.create(bind=bind, checkfirst=True)
    InvestmentEntry.__table__.create(bind=bind, checkfirst=True)


def sanitize_report_months(months: int | None) -> int:
    try:
        value = int(months or 6)
    except Exception:
        return 6
    return value if value in REPORT_WINDOWS else 6


def previous_month(competence: str) -> str:
    year, month = [int(x) for x in competence.split("-")]
    month -= 1
    if month == 0:
        month = 12
        year -= 1
    return f"{year:04d}-{month:02d}"


def _clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _opening_competence(account: InvestmentAccount) -> str:
    return account.opening_date.strftime("%Y-%m")


def _signed_amount(kind: str, amount: float) -> float:
    value = float(amount or 0.0)
    normalized_kind = (kind or "").strip().upper()
    if normalized_kind == "RESGATE":
        return -abs(value)
    if normalized_kind in {"APORTE", "RENDIMENTO"}:
        return abs(value)
    return value


def list_accounts(db: Session, *, active_only: bool = False) -> list[InvestmentAccount]:
    ensure_investment_schema(db)
    qry = db.query(InvestmentAccount)
    if active_only:
        qry = qry.filter(InvestmentAccount.is_active.is_(True))
    return qry.order_by(InvestmentAccount.is_active.desc(), InvestmentAccount.name.asc()).all()


def create_account(
    db: Session,
    *,
    name: str,
    institution: str | None = None,
    account_number: str | None = None,
    opening_balance: float = 0.0,
    opening_date: date,
    notes: str | None = None,
) -> InvestmentAccount:
    ensure_investment_schema(db)
    account = InvestmentAccount(
        name=name.strip(),
        institution=_clean_text(institution),
        account_number=_clean_text(account_number),
        opening_balance=float(opening_balance or 0.0),
        opening_date=opening_date,
        notes=_clean_text(notes),
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def toggle_account_active(db: Session, account_id: int) -> InvestmentAccount | None:
    ensure_investment_schema(db)
    account = db.get(InvestmentAccount, account_id)
    if not account:
        return None
    account.is_active = not bool(account.is_active)
    db.commit()
    db.refresh(account)
    return account


def list_entries(
    db: Session,
    *,
    competence: str | None = None,
    start_ym: str | None = None,
    end_ym: str | None = None,
    account_id: int | None = None,
    kind: str | None = None,
    q: str | None = None,
    limit: int = 500,
) -> list[InvestmentEntry]:
    ensure_investment_schema(db)
    qry = (
        db.query(InvestmentEntry)
        .join(InvestmentEntry.account)
        .options(joinedload(InvestmentEntry.account))
    )

    if competence:
        qry = qry.filter(InvestmentEntry.competence_month == competence)
    if start_ym:
        qry = qry.filter(InvestmentEntry.competence_month >= start_ym)
    if end_ym:
        qry = qry.filter(InvestmentEntry.competence_month <= end_ym)
    if account_id:
        qry = qry.filter(InvestmentEntry.investment_account_id == account_id)
    if kind:
        qry = qry.filter(InvestmentEntry.kind == kind)
    if q:
        like = f"%{q.strip()}%"
        qry = qry.filter(
            InvestmentEntry.description.ilike(like)
            | InvestmentEntry.notes.ilike(like)
            | InvestmentEntry.reference_month.ilike(like)
            | InvestmentAccount.name.ilike(like)
            | InvestmentAccount.institution.ilike(like)
        )

    return qry.order_by(InvestmentEntry.entry_date.desc(), InvestmentEntry.id.desc()).limit(limit).all()


def create_entry(
    db: Session,
    *,
    investment_account_id: int,
    competence: str,
    entry_date: date,
    kind: str,
    amount: float,
    description: str,
    reference_month: str | None = None,
    notes: str | None = None,
) -> InvestmentEntry:
    ensure_investment_schema(db)
    normalized_kind = (kind or "").strip().upper()
    if normalized_kind not in ENTRY_KINDS:
        raise ValueError("Tipo de movimento invalido.")

    account = db.get(InvestmentAccount, investment_account_id)
    if not account:
        raise ValueError("Conta de investimento nao encontrada.")

    value = float(amount or 0.0)
    if normalized_kind in {"APORTE", "RESGATE", "RENDIMENTO"}:
        value = abs(value)

    entry = InvestmentEntry(
        investment_account_id=investment_account_id,
        competence_month=competence,
        entry_date=entry_date,
        kind=normalized_kind,
        amount=value,
        description=description.strip(),
        reference_month=_clean_text(reference_month),
        notes=_clean_text(notes),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def delete_entry(db: Session, entry_id: int) -> bool:
    ensure_investment_schema(db)
    entry = db.get(InvestmentEntry, entry_id)
    if not entry:
        return False
    db.delete(entry)
    db.commit()
    return True


def account_positions(
    db: Session,
    *,
    competence: str,
    account_id: int | None = None,
    include_inactive: bool = True,
) -> list[dict]:
    ensure_investment_schema(db)
    accounts = list_accounts(db, active_only=not include_inactive)
    if account_id:
        accounts = [account for account in accounts if account.id == account_id]
    if not accounts:
        return []

    account_ids = [account.id for account in accounts]
    entries = (
        db.query(InvestmentEntry)
        .options(joinedload(InvestmentEntry.account))
        .filter(
            InvestmentEntry.investment_account_id.in_(account_ids),
            InvestmentEntry.competence_month <= competence,
        )
        .order_by(InvestmentEntry.entry_date.asc(), InvestmentEntry.id.asc())
        .all()
    )

    grouped: dict[int, list[InvestmentEntry]] = defaultdict(list)
    for entry in entries:
        grouped[int(entry.investment_account_id)].append(entry)

    previous_comp = previous_month(competence)
    positions: list[dict] = []

    for account in accounts:
        opening_month = _opening_competence(account)
        opening_value = float(account.opening_balance or 0.0)
        current_balance = opening_value if opening_month <= competence else 0.0
        previous_balance = opening_value if opening_month <= previous_comp else 0.0
        monthly = {
            "aportes": opening_value if opening_month == competence else 0.0,
            "resgates": 0.0,
            "rendimentos": 0.0,
            "ajustes": 0.0,
        }

        for entry in grouped.get(account.id, []):
            signed = _signed_amount(entry.kind, float(entry.amount or 0.0))
            current_balance += signed
            if entry.competence_month <= previous_comp:
                previous_balance += signed
            if entry.competence_month == competence:
                if entry.kind == "APORTE":
                    monthly["aportes"] += abs(float(entry.amount or 0.0))
                elif entry.kind == "RESGATE":
                    monthly["resgates"] += abs(float(entry.amount or 0.0))
                elif entry.kind == "RENDIMENTO":
                    monthly["rendimentos"] += abs(float(entry.amount or 0.0))
                else:
                    monthly["ajustes"] += float(entry.amount or 0.0)

        positions.append(
            {
                "account": account,
                "balance": current_balance,
                "previous_balance": previous_balance,
                "delta": current_balance - previous_balance,
                "monthly": monthly,
            }
        )

    return positions


def investment_report(
    db: Session,
    *,
    end_ym: str,
    months: int = 6,
    account_id: int | None = None,
) -> dict:
    ensure_investment_schema(db)
    window = sanitize_report_months(months)

    year, month = [int(x) for x in end_ym.split("-")]
    for _ in range(max(0, window - 1)):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    start_ym = f"{year:04d}-{month:02d}"

    accounts = list_accounts(db, active_only=False)
    if account_id:
        accounts = [account for account in accounts if account.id == account_id]
    if not accounts:
        return {
            "start": start_ym,
            "end": end_ym,
            "months": window,
            "series": [],
            "totals": {"aportes": 0.0, "resgates": 0.0, "rendimentos": 0.0, "ajustes": 0.0, "saldo": 0.0},
            "accounts_count": 0,
        }

    account_ids = [account.id for account in accounts]
    all_entries = (
        db.query(InvestmentEntry)
        .options(joinedload(InvestmentEntry.account))
        .filter(
            InvestmentEntry.investment_account_id.in_(account_ids),
            InvestmentEntry.competence_month <= end_ym,
        )
        .order_by(InvestmentEntry.entry_date.asc(), InvestmentEntry.id.asc())
        .all()
    )

    entries_by_month: dict[str, list[InvestmentEntry]] = defaultdict(list)
    opening_by_month: dict[str, float] = defaultdict(float)
    running_balance = 0.0

    for account in accounts:
        opening_month = _opening_competence(account)
        opening_value = float(account.opening_balance or 0.0)
        if opening_month < start_ym:
            running_balance += opening_value
        elif start_ym <= opening_month <= end_ym:
            opening_by_month[opening_month] += opening_value

    for entry in all_entries:
        signed = _signed_amount(entry.kind, float(entry.amount or 0.0))
        if entry.competence_month < start_ym:
            running_balance += signed
        elif start_ym <= entry.competence_month <= end_ym:
            entries_by_month[entry.competence_month].append(entry)

    totals = {"aportes": 0.0, "resgates": 0.0, "rendimentos": 0.0, "ajustes": 0.0, "saldo": running_balance}
    series: list[dict] = []

    for ym in month_range(start_ym, end_ym):
        aportes = float(opening_by_month.get(ym, 0.0))
        resgates = 0.0
        rendimentos = 0.0
        ajustes = 0.0

        for entry in entries_by_month.get(ym, []):
            amount = float(entry.amount or 0.0)
            if entry.kind == "APORTE":
                aportes += abs(amount)
            elif entry.kind == "RESGATE":
                resgates += abs(amount)
            elif entry.kind == "RENDIMENTO":
                rendimentos += abs(amount)
            else:
                ajustes += amount

        running_balance += aportes + rendimentos + ajustes - resgates
        series.append(
            {
                "competence": ym,
                "aportes": aportes,
                "resgates": resgates,
                "rendimentos": rendimentos,
                "ajustes": ajustes,
                "saldo": running_balance,
            }
        )
        totals["aportes"] += aportes
        totals["resgates"] += resgates
        totals["rendimentos"] += rendimentos
        totals["ajustes"] += ajustes
        totals["saldo"] = running_balance

    return {
        "start": start_ym,
        "end": end_ym,
        "months": window,
        "series": series,
        "totals": totals,
        "accounts_count": len(accounts),
    }
