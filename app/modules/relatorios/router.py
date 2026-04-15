from __future__ import annotations

import csv
import io
from io import StringIO
from typing import Iterable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.templating import templates
from app.core.utils import clamp_competence, current_competence
from app.modules.auth.utils import require_login
from app.modules.relatorios.service import (
    close_month,
    generate_lancamentos_pdf_export,
    generate_periodo_pdf_snapshot,
    get_or_create_monthly_close,
    latest_demonstrativo,
    list_lancamentos_for_export,
    periodo_report,
)
from app.modules.relatorios.boleto_receber_pdf import boleto_receber_report_pdf_bytes
from app.modules.relatorios.boleto_receber_reports import (
    build_boleto_receber_report,
    build_boleto_receber_report_bundle,
)

from app.modules.rateio.service import compute_divisao_custos
from app.modules.rateio.pdf_summary import generate_rateio_summary_pdf_bytes

router = APIRouter(prefix="/relatorios", tags=["relatorios"])


DEFAULT_FIELDS = [
    "id",
    "competence_month",
    "entry_date",
    "kind",
    "status",
    "amount",
    "description",
    "document_number",
    "category",
    "cost_center",
    "bank_account_id",
    "customer_id",
    "notes",
    "created_at",
]


def _csv_stream(rows: list[dict], fieldnames: list[str]) -> Iterable[bytes]:
    """Gera CSV (UTF-8 com BOM) em streaming para melhor compatibilidade com Excel."""
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, delimiter=";")

    writer.writeheader()
    header_chunk = output.getvalue()
    output.seek(0)
    output.truncate(0)
    yield ("\ufeff" + header_chunk).encode("utf-8")

    for r in rows:
        # garante que todas as chaves existam
        safe = {k: ("" if r.get(k) is None else r.get(k)) for k in fieldnames}
        writer.writerow(safe)
        chunk = output.getvalue()
        output.seek(0)
        output.truncate(0)
        if chunk:
            yield chunk.encode("utf-8")


def _csv_response(payload: dict, filename: str) -> StreamingResponse:
    rows = payload.get("rows", []) or []
    fieldnames = payload.get("fieldnames") or (list(rows[0].keys()) if rows else DEFAULT_FIELDS)

    return StreamingResponse(
        _csv_stream(rows, fieldnames),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("")
@router.get("/")
def relatorios_home(
    request: Request,
    end: str | None = None,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    """Painel de relatórios (cards) — acessado ao clicar em "Relatórios"."""
    competence = clamp_competence(end, fallback=current_competence()) or current_competence()
    close = get_or_create_monthly_close(db, competence)

    return templates.TemplateResponse(
        "relatorios/index.html",
        {
            "request": request,
            "user": user,
            "competence": competence,
            "close": close,
        },
    )


@router.get("/boletos-receber")
def relatorios_boletos_receber_page(
    request: Request,
    competence: str | None = None,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = clamp_competence(competence, fallback=current_competence()) or current_competence()
    data = build_boleto_receber_report_bundle(db, competence)
    return templates.TemplateResponse(
        "relatorios/boletos_receber.html",
        {
            "request": request,
            "user": user,
            "competence": competence,
            "data": data,
        },
    )


@router.get("/boletos-receber/export.csv")
def export_boletos_receber_csv(
    competence: str,
    report: str = "all",
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = clamp_competence(competence) or competence
    payload = build_boleto_receber_report(db, competence, report)
    return _csv_response(
        {
            "rows": payload.get("csv_rows") or [],
            "fieldnames": [column["label"] for column in (payload.get("pdf_columns") or [])],
        },
        f"{payload['filename_base']}.csv",
    )


@router.get("/boletos-receber/export.pdf")
def export_boletos_receber_pdf(
    competence: str,
    report: str = "all",
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = clamp_competence(competence) or competence
    payload = build_boleto_receber_report(db, competence, report)
    pdf_bytes = boleto_receber_report_pdf_bytes(payload)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{payload["filename_base"]}.pdf"'},
    )


@router.get("/fechamento")
def fechamento_page(
    request: Request,
    competence: str | None = None,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = clamp_competence(competence, fallback=current_competence()) or current_competence()
    close = get_or_create_monthly_close(db, competence)
    snap = latest_demonstrativo(db, competence)
    return templates.TemplateResponse(
        "relatorios/fechamento.html",
        {"request": request, "user": user, "competence": competence, "close": close, "snap": snap},
    )


@router.post("/api/{competence}/fechar")
def api_fechar(competence: str, user=Depends(require_login), db: Session = Depends(get_db)):
    competence = clamp_competence(competence) or competence
    return close_month(db, competence)


@router.get("/fechamento/pdf")
def download_fechamento_pdf(competence: str, user=Depends(require_login), db: Session = Depends(get_db)):
    competence = clamp_competence(competence) or competence
    snap = latest_demonstrativo(db, competence)
    if not snap or not snap.pdf_path:
        return {"error": "Fechamento não gerado"}
    return FileResponse(path=snap.pdf_path, filename=f"demonstrativo_{competence}.pdf", media_type="application/pdf")


@router.get("/periodo")
def periodo_page(
    request: Request,
    end: str | None = None,
    months: int = 6,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    end = clamp_competence(end, fallback=current_competence()) or current_competence()
    data = periodo_report(db, end_ym=end, months=months)
    return templates.TemplateResponse(
        "relatorios/periodo.html",
        {"request": request, "user": user, "competence": end, "data": data},
    )


@router.get("/periodo/pdf")
def periodo_pdf(end: str | None = None, months: int = 6, user=Depends(require_login), db: Session = Depends(get_db)):
    end = clamp_competence(end, fallback=current_competence()) or current_competence()
    path = generate_periodo_pdf_snapshot(db, end_ym=end, months=months)
    fname = f"relatorio_periodo_{end}_{months}m.pdf"
    return FileResponse(path=path, filename=fname, media_type="application/pdf")


@router.get("/export/entradas.csv")
def export_entradas_csv(
    start: str | None = None,
    end: str | None = None,
    status: str | None = None,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    start = clamp_competence(start) if start else None
    end = clamp_competence(end) if end else None
    payload = list_lancamentos_for_export(db, kind="ENTRADA", start_ym=start, end_ym=end, status=status)
    fname = "entradas.csv" if not (start or end or status) else f"entradas_{start or 'ini'}_{end or 'fim'}_{status or 'todos'}.csv"
    return _csv_response(payload, fname)


@router.get("/export/saidas.csv")
def export_saidas_csv(
    start: str | None = None,
    end: str | None = None,
    status: str | None = None,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    start = clamp_competence(start) if start else None
    end = clamp_competence(end) if end else None
    payload = list_lancamentos_for_export(db, kind="SAIDA", start_ym=start, end_ym=end, status=status)
    fname = "saidas.csv" if not (start or end or status) else f"saidas_{start or 'ini'}_{end or 'fim'}_{status or 'todos'}.csv"
    return _csv_response(payload, fname)


@router.get("/export/completo.csv")
def export_completo_csv(
    start: str | None = None,
    end: str | None = None,
    status: str | None = None,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    start = clamp_competence(start) if start else None
    end = clamp_competence(end) if end else None
    payload = list_lancamentos_for_export(db, kind=None, start_ym=start, end_ym=end, status=status)
    fname = "relatorio_completo.csv" if not (start or end or status) else f"relatorio_completo_{start or 'ini'}_{end or 'fim'}_{status or 'todos'}.csv"
    return _csv_response(payload, fname)


@router.get("/export/entradas.pdf")
def export_entradas_pdf(
    start: str | None = None,
    end: str | None = None,
    status: str | None = None,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    start = clamp_competence(start) if start else None
    end = clamp_competence(end) if end else None
    path = generate_lancamentos_pdf_export(
        db,
        kind="ENTRADA",
        start_ym=start,
        end_ym=end,
        status=status,
        title="Relatório de Entradas (MVP)",
    )
    return FileResponse(path=path, filename="entradas.pdf", media_type="application/pdf")


@router.get("/export/saidas.pdf")
def export_saidas_pdf(
    start: str | None = None,
    end: str | None = None,
    status: str | None = None,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    start = clamp_competence(start) if start else None
    end = clamp_competence(end) if end else None
    path = generate_lancamentos_pdf_export(
        db,
        kind="SAIDA",
        start_ym=start,
        end_ym=end,
        status=status,
        title="Relatório de Saídas (MVP)",
    )
    return FileResponse(path=path, filename="saidas.pdf", media_type="application/pdf")


@router.get("/export/completo.pdf")
def export_completo_pdf(
    start: str | None = None,
    end: str | None = None,
    status: str | None = None,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    start = clamp_competence(start) if start else None
    end = clamp_competence(end) if end else None
    path = generate_lancamentos_pdf_export(
        db,
        kind=None,
        start_ym=start,
        end_ym=end,
        status=status,
        title="Relatório Completo (MVP)",
    )
    return FileResponse(path=path, filename="relatorio_completo.pdf", media_type="application/pdf")


@router.get("/rateio/resumo.pdf")
def export_rateio_resumo_pdf(
    competence: str,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    """Gera um PDF resumo da divisão de custos (quanto cada construtora vai pagar)."""

    preview = compute_divisao_custos(db=db, competence=competence)
    pdf_bytes = generate_rateio_summary_pdf_bytes(preview)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=rateio_resumo_{competence}.pdf"},
    )
