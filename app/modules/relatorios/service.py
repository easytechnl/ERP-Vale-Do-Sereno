from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from app.models.relatorios import MonthlyClose, ReportSnapshot
from app.models.lancamentos import LedgerEntry
from app.core.storage import competence_dir
from app.modules.relatorios.pdf import generate_demonstrativo_pdf, generate_periodo_pdf
from app.modules.lancamentos.service import month_range, series_by_month, totals_for_period

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
    """Resumo por período (ex.: 1, 6, 12 meses)."""
    # calcula start_ym a partir de end_ym e months
    y, m = [int(x) for x in end_ym.split("-")]
    # volta (months-1) meses
    for _ in range(max(0, months - 1)):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    start_ym = f"{y:04d}-{m:02d}"

    totals = totals_for_period(db, start_ym=start_ym, end_ym=end_ym)
    series = series_by_month(db, start_ym=start_ym, end_ym=end_ym)
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
