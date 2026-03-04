from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from app.models.relatorios import MonthlyClose, ReportSnapshot
from app.models.lancamentos import LedgerEntry
from app.models.conciliacao import BankStatementImport, BankTransaction
from app.core.storage import competence_dir, storage_root
from app.modules.relatorios.pdf import generate_demonstrativo_pdf, generate_periodo_pdf, generate_lancamentos_pdf
from app.modules.lancamentos.service import ensure_ledger_entries_schema, month_range, series_by_month, totals_for_period



def _latest_statement_import_ids(db: Session, *, start_ym: str | None, end_ym: str | None) -> list[int]:
    """Retorna os IDs dos últimos extratos importados (um por competência) dentro do intervalo."""
    qry = db.query(
        BankStatementImport.competence_month,
        func.max(BankStatementImport.id).label("max_id"),
    )
    if start_ym:
        qry = qry.filter(BankStatementImport.competence_month >= start_ym)
    if end_ym:
        qry = qry.filter(BankStatementImport.competence_month <= end_ym)
    qry = qry.group_by(BankStatementImport.competence_month)
    rows = qry.all()
    return [int(r.max_id) for r in rows if getattr(r, "max_id", None)]


def list_extrato_for_export(
    db: Session,
    *,
    kind: str | None = None,
    start_ym: str | None = None,
    end_ym: str | None = None,
) -> dict:
    """Retorna transações do extrato (OFX) para exportação.

    Mantém o mesmo contrato de "list_lancamentos_for_export" para reuso do CSV/PDF.
    """
    ids = _latest_statement_import_ids(db, start_ym=start_ym, end_ym=end_ym)
    if not ids:
        return {
            "source": "EXTRATO",
            "totals": {"entradas": 0.0, "saidas": 0.0, "saldo": 0.0},
            "rows": [],
            "count": 0,
            "filters": {"kind": kind, "start_ym": start_ym, "end_ym": end_ym, "status": None},
        }

    # junta transações com o import para conseguir a competência
    qry = (
        db.query(BankTransaction, BankStatementImport)
        .join(BankStatementImport, BankStatementImport.id == BankTransaction.import_id)
        .filter(BankTransaction.import_id.in_(ids))
    )

    if kind == "ENTRADA":
        qry = qry.filter(func.lower(func.coalesce(BankTransaction.kind, "")) == "credit")
    elif kind == "SAIDA":
        qry = qry.filter(func.lower(func.coalesce(BankTransaction.kind, "")) == "debit")

    items = qry.order_by(BankTransaction.txn_date.asc(), BankTransaction.id.asc()).all()

    entradas = 0.0
    saidas = 0.0
    rows: list[dict] = []

    for txn, imp in items:
        k = (txn.kind or "").lower().strip()
        amount = float(txn.amount or 0)
        abs_amount = abs(amount)

        if k == "credit":
            entradas += abs_amount
            kind_label = "ENTRADA"
        elif k == "debit":
            saidas += abs_amount
            kind_label = "SAIDA"
        else:
            # fallback: usa sinal
            if amount >= 0:
                entradas += abs_amount
                kind_label = "ENTRADA"
            else:
                saidas += abs_amount
                kind_label = "SAIDA"

        notes = ""
        if txn.fit_id:
            notes = f"FITID: {txn.fit_id}"

        # BankTransaction não possui created_at. Para manter contrato de exportação,
        # usamos imported_at do import (quando disponível) como referência.
        imported_at = getattr(imp, "imported_at", None)

        rows.append(
            {
                "id": txn.id,
                "competence_month": getattr(imp, "competence_month", "") or "",
                "entry_date": (txn.txn_date.strftime("%d/%m/%Y") if txn.txn_date else ""),
                "kind": kind_label,
                "status": "EXTRATO",
                "amount": abs_amount,
                "description": txn.description or "",
                "document_number": "",
                "category": "",
                "cost_center": "",
                "bank_account_id": "",
                "customer_id": "",
                "notes": notes,
                "created_at": imported_at.isoformat() if imported_at else "",
                "import_id": txn.import_id,
                "fit_id": (txn.fit_id or ""),
                "source_type": getattr(imp, "source_type", "") or "",
            }
        )

    return {
        "source": "EXTRATO",
        "totals": {"entradas": entradas, "saidas": saidas, "saldo": entradas - saidas},
        "rows": rows,
        "count": len(rows),
        "filters": {"kind": kind, "start_ym": start_ym, "end_ym": end_ym, "status": None},
    }


def list_lancamentos_for_export(
    db: Session,
    *,
    kind: str | None = None,
    start_ym: str | None = None,
    end_ym: str | None = None,
    status: str | None = None,
) -> dict:
    """Retorna lançamentos e totais para exportação.

    - kind: ENTRADA, SAIDA ou None (ambos)
    - start_ym/end_ym: filtro por competência (YYYY-MM)
    - status: PREVISTO/REALIZADO ou None (ambos)
    """
    # Preferência: se existir extrato (OFX) importado no período, exporta com base nele.
    ensure_ledger_entries_schema(db)
    extrato = list_extrato_for_export(db, kind=kind, start_ym=start_ym, end_ym=end_ym)
    if extrato.get('count', 0) > 0:
        # mantém status no filtro, mas a origem é o extrato (não há PREVISTO/REALIZADO).
        extrato['filters']['status'] = status
        return extrato

    qry = db.query(LedgerEntry)
    if kind:
        qry = qry.filter(LedgerEntry.kind == kind)
    if status:
        qry = qry.filter(LedgerEntry.status == status)
    if start_ym:
        qry = qry.filter(LedgerEntry.competence_month >= start_ym)
    if end_ym:
        qry = qry.filter(LedgerEntry.competence_month <= end_ym)

    items = qry.order_by(LedgerEntry.entry_date.asc(), LedgerEntry.id.asc()).all()

    entradas = sum(float(x.amount) for x in items if x.kind == "ENTRADA")
    saidas = sum(float(x.amount) for x in items if x.kind == "SAIDA")

    rows: list[dict] = []
    for x in items:
        rows.append(
            {
                "id": x.id,
                "competence_month": x.competence_month,
                "entry_date": x.entry_date.isoformat() if x.entry_date else "",
                "kind": x.kind,
                "status": x.status,
                "amount": float(x.amount),
                "description": x.description,
                "document_number": x.document_number or "",
                "category": x.category or "",
                "cost_center": x.cost_center or "",
                "bank_account_id": x.bank_account_id or "",
                "customer_id": x.customer_id or "",
                "notes": (x.notes or "").replace("\n", " ").strip(),
                "created_at": x.created_at.isoformat() if x.created_at else "",
            }
        )

    return {
        "totals": {"entradas": entradas, "saidas": saidas, "saldo": entradas - saidas},
        "rows": rows,
        "count": len(rows),
        "filters": {"kind": kind, "start_ym": start_ym, "end_ym": end_ym, "status": status},
    }


def generate_lancamentos_pdf_export(
    db: Session,
    *,
    kind: str | None = None,
    start_ym: str | None = None,
    end_ym: str | None = None,
    status: str | None = None,
    title: str = "Relatório de Lançamentos (MVP)",
) -> str:
    """Gera um PDF de exportação (entradas/saídas/completo) e retorna o caminho."""
    payload = list_lancamentos_for_export(db, kind=kind, start_ym=start_ym, end_ym=end_ym, status=status)

    out_dir = storage_root() / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    suffix = (kind or "COMPLETO").lower()
    pdf_path = out_dir / f"{stamp}_lancamentos_{suffix}.pdf"

    filt = payload["filters"]
    subtitle = ""
    if filt.get("start_ym") or filt.get("end_ym"):
        subtitle = f"Competência: {filt.get('start_ym') or '...'} → {filt.get('end_ym') or '...'}"
    else:
        subtitle = "Exportação completa (sem filtro de competência)"
    if filt.get("status"):
        subtitle += f" | Status: {filt['status']}"

    generate_lancamentos_pdf(
        pdf_path,
        title=title,
        subtitle=subtitle,
        totals=payload["totals"],
        rows=payload["rows"],
    )
    return str(pdf_path)

def get_or_create_monthly_close(db: Session, competence: str) -> MonthlyClose:
    close = db.query(MonthlyClose).filter(MonthlyClose.competence_month == competence).first()
    if not close:
        close = MonthlyClose(competence_month=competence, status="ABERTO")
        db.add(close)
        db.commit()
        db.refresh(close)
    return close

def is_closed(db: Session, competence: str) -> bool:
    close = get_or_create_monthly_close(db, competence)
    return close.status == "FECHADO"

def close_month(db: Session, competence: str) -> dict:
    ensure_ledger_entries_schema(db)
    close = get_or_create_monthly_close(db, competence)
    if close.status == "FECHADO":
        return {"status": "already_closed", "competence": competence}

    # MVP: fechamento baseado em lançamentos (REALIZADO)
    items = (
        db.query(LedgerEntry)
        .filter(and_(LedgerEntry.competence_month == competence, LedgerEntry.status == "REALIZADO"))
        .order_by(LedgerEntry.entry_date.asc(), LedgerEntry.id.asc())
        .all()
    )

    entradas = sum(float(x.amount) for x in items if x.kind == "ENTRADA")
    saidas = sum(float(x.amount) for x in items if x.kind == "SAIDA")
    saldo = entradas - saidas

    lines = [
        {
            "date": x.entry_date.isoformat(),
            "name": x.description,
            "amount": float(x.amount) * (1 if x.kind == "ENTRADA" else -1),
            "kind": x.kind,
            "category": x.category,
            "cost_center": x.cost_center,
        }
        for x in items
    ]

    payload = {"entradas": entradas, "saidas": saidas, "saldo": saldo, "lines": lines}

    out_dir = competence_dir(competence) / "fechamento"
    pdf_path = out_dir / f"demonstrativo_{competence}.pdf"
    generate_demonstrativo_pdf(
        pdf_path,
        competence=competence,
        totals={"entradas": entradas, "saidas": saidas, "saldo": saldo},
        lines=lines,
    )

    snap = ReportSnapshot(
        monthly_close_id=close.id,
        report_type="demonstrativo",
        payload_json=payload,
        pdf_path=str(pdf_path),
    )
    db.add(snap)

    close.status = "FECHADO"
    close.closed_at = datetime.now(timezone.utc)
    db.commit()

    return {"status": "closed", "competence": competence, "pdf_path": str(pdf_path), "totals": {"entradas": entradas, "saidas": saidas, "saldo": saldo}}


def periodo_report(db: Session, *, end_ym: str, months: int = 1) -> dict:
    """Resumo por período (ex.: 1, 6, 12 meses).

    Regra: se existir extrato OFX importado na competência, usa o extrato como fonte de verdade.
    Caso contrário, usa lançamentos (status REALIZADO).
    """
    # calcula start_ym a partir de end_ym e months
    y, m = [int(x) for x in end_ym.split("-")]
    for _ in range(max(0, months - 1)):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    start_ym = f"{y:04d}-{m:02d}"

    months_list = month_range(start_ym, end_ym)
    series: list[dict] = []

    tot_entradas = 0.0
    tot_saidas = 0.0

    for ym in months_list:
        st = statement_totals_for_competence(db, ym)
        if st.get("has_statement"):
            entradas = float(st.get("entradas", 0.0))
            saidas = float(st.get("saidas", 0.0))
            source = "EXTRATO"
        else:
            t = totals_for_period(db, start_ym=ym, end_ym=ym)
            entradas = float(t.get("entradas", 0.0))
            saidas = float(t.get("saidas", 0.0))
            source = "LANÇAMENTOS"

        saldo = entradas - saidas
        series.append({"competence": ym, "entradas": entradas, "saidas": saidas, "saldo": saldo, "source": source})
        tot_entradas += entradas
        tot_saidas += saidas

    totals = {"entradas": tot_entradas, "saidas": tot_saidas, "saldo": tot_entradas - tot_saidas}
    return {"start": start_ym, "end": end_ym, "months": months, "totals": totals, "series": series}


def generate_periodo_pdf_snapshot(db: Session, *, end_ym: str, months: int = 6) -> str:
    data = periodo_report(db, end_ym=end_ym, months=months)
    out_dir = competence_dir(end_ym) / "relatorios"
    pdf_path = out_dir / f"relatorio_periodo_{data['start']}_a_{data['end']}.pdf"
    generate_periodo_pdf(pdf_path, data=data)
    return str(pdf_path)

def latest_demonstrativo(db: Session, competence: str) -> ReportSnapshot | None:
    close = get_or_create_monthly_close(db, competence)
    snap = (
        db.query(ReportSnapshot)
        .filter(ReportSnapshot.monthly_close_id == close.id, ReportSnapshot.report_type == "demonstrativo")
        .order_by(ReportSnapshot.id.desc())
        .first()
    )
    return snap


def generate_lancamentos_export_pdf(
    db: Session,
    *,
    kind: str | None,
    start_ym: str | None = None,
    end_ym: str | None = None,
    status: str | None = None,
) -> str:
    """Gera PDF para exportação (entradas, saídas ou completo) e retorna o caminho."""
    data = list_lancamentos_for_export(db, kind=kind, start_ym=start_ym, end_ym=end_ym, status=status)
    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    export_dir = storage_root() / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    label = "completo" if kind is None else ("entradas" if kind == "ENTRADA" else "saidas")
    rng = ""
    if start_ym or end_ym:
        rng = f"_{start_ym or 'inicio'}_a_{end_ym or 'fim'}"

    out = export_dir / f"relatorio_{label}{rng}_{now}.pdf"
    subtitle = "Lançamentos (exportação)"
    if start_ym or end_ym:
        subtitle += f" — Competência {start_ym or '...'} → {end_ym or '...'}"
    if status:
        subtitle += f" — Status: {status}"

    title = "Relatório Completo" if kind is None else ("Relatório de Entradas" if kind == "ENTRADA" else "Relatório de Saídas")
    generate_lancamentos_pdf(
        out,
        title=title,
        subtitle=subtitle,
        totals=data["totals"],
        rows=data["rows"],
        limit=350,
    )
    return str(out)
