from __future__ import annotations

import csv
from datetime import date
from io import StringIO
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.templating import templates
from app.core.utils import normalize_competence
from app.modules.auth.utils import require_login
from app.modules.investimentos.pdf import investments_report_pdf_bytes
from app.modules.investimentos.service import (
    account_positions,
    create_account,
    create_entry,
    delete_entry,
    ensure_investment_schema,
    investment_report,
    list_accounts,
    list_entries,
    sanitize_report_months,
    toggle_account_active,
)


router = APIRouter(prefix="/investimentos", tags=["investimentos"])

KIND_LABELS = {
    "APORTE": "Aporte",
    "RESGATE": "Resgate",
    "RENDIMENTO": "Rendimento",
    "AJUSTE": "Ajuste",
}


def _page_url(
    *,
    competence: str,
    account_id: int | None = None,
    kind: str | None = None,
    q: str | None = None,
    months: int = 6,
    ok: str | None = None,
    error: str | None = None,
    anchor: str | None = None,
) -> str:
    params: dict[str, str | int] = {
        "competence": competence,
        "months": sanitize_report_months(months),
    }
    if account_id:
        params["account_id"] = account_id
    if kind:
        params["kind"] = kind
    if q:
        params["q"] = q
    if ok:
        params["ok"] = ok
    if error:
        params["error"] = error
    url = f"/investimentos?{urlencode(params)}"
    if anchor:
        url += anchor
    return url


def _empty_month_row(competence: str) -> dict:
    return {
        "competence": competence,
        "aportes": 0.0,
        "resgates": 0.0,
        "rendimentos": 0.0,
        "ajustes": 0.0,
        "saldo": 0.0,
    }


@router.get("")
@router.get("/")
def investimentos_page(
    request: Request,
    competence: str | None = None,
    account_id: int | None = None,
    kind: str | None = None,
    q: str | None = None,
    months: int = 6,
    ok: str | None = None,
    error: str | None = None,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    if not competence:
        competence = date.today().strftime("%Y-%m")
    competence = normalize_competence(competence) or competence
    months = sanitize_report_months(months)

    ensure_investment_schema(db)
    accounts = list_accounts(db, active_only=False)
    selected_account = next((account for account in accounts if account.id == account_id), None)
    if account_id and not selected_account:
        account_id = None

    entries = list_entries(
        db,
        competence=competence,
        account_id=account_id,
        kind=kind,
        q=q,
    )
    positions = account_positions(db, competence=competence, include_inactive=True)
    report = investment_report(db, end_ym=competence, months=months, account_id=account_id)

    current_row = report["series"][-1] if report["series"] else _empty_month_row(competence)
    previous_row = report["series"][-2] if len(report["series"]) > 1 else _empty_month_row(competence)

    summary = {
        "scope": selected_account.name if selected_account else "Todas as contas de investimento",
        "accounts_count": report.get("accounts_count", 0),
        "active_accounts": len([item for item in positions if item["account"].is_active]),
        "saldo": float(current_row.get("saldo") or 0.0),
        "aportes": float(current_row.get("aportes") or 0.0),
        "resgates": float(current_row.get("resgates") or 0.0),
        "rendimentos": float(current_row.get("rendimentos") or 0.0),
        "ajustes": float(current_row.get("ajustes") or 0.0),
        "delta": float(current_row.get("saldo") or 0.0) - float(previous_row.get("saldo") or 0.0),
    }

    return templates.TemplateResponse(
        "investimentos/index.html",
        {
            "request": request,
            "user": user,
            "competence": competence,
            "accounts": accounts,
            "selected_account": selected_account,
            "entries": entries,
            "positions": positions,
            "report": report,
            "summary": summary,
            "filters": {
                "account_id": account_id,
                "kind": kind,
                "q": q,
                "months": months,
            },
            "kind_labels": KIND_LABELS,
            "ok": ok,
            "error": error,
        },
    )


@router.post("/contas")
def investimentos_create_account(
    competence: str = Form(...),
    months: int = Form(6),
    name: str = Form(...),
    institution: str | None = Form(None),
    account_number: str | None = Form(None),
    opening_balance: float = Form(0.0),
    opening_date: str = Form(...),
    notes: str | None = Form(None),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = normalize_competence(competence) or competence
    try:
        parsed_opening_date = date.fromisoformat(opening_date)
    except Exception:
        parsed_opening_date = date.today()

    if not name.strip():
        return RedirectResponse(
            _page_url(competence=competence, months=months, error="Informe o nome da conta.", anchor="#contas"),
            status_code=303,
        )

    create_account(
        db,
        name=name,
        institution=institution,
        account_number=account_number,
        opening_balance=opening_balance,
        opening_date=parsed_opening_date,
        notes=notes,
    )
    return RedirectResponse(
        _page_url(competence=competence, months=months, ok="Conta de investimento criada.", anchor="#contas"),
        status_code=303,
    )


@router.post("/contas/{account_id}/toggle")
def investimentos_toggle_account(
    account_id: int,
    competence: str = Form(...),
    months: int = Form(6),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = normalize_competence(competence) or competence
    account = toggle_account_active(db, account_id)
    if not account:
        return RedirectResponse(
            _page_url(competence=competence, months=months, error="Conta nao encontrada.", anchor="#contas"),
            status_code=303,
        )
    status = "ativada" if account.is_active else "desativada"
    return RedirectResponse(
        _page_url(competence=competence, months=months, ok=f"Conta {status}.", anchor="#contas"),
        status_code=303,
    )


@router.post("/movimentos")
def investimentos_create_entry(
    competence: str = Form(...),
    months: int = Form(6),
    investment_account_id: int = Form(...),
    entry_date: str = Form(...),
    kind: str = Form(...),
    amount: float = Form(...),
    description: str = Form(...),
    reference_month: str | None = Form(None),
    notes: str | None = Form(None),
    filter_account_id: int | None = Form(None),
    filter_kind: str | None = Form(None),
    filter_q: str | None = Form(None),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = normalize_competence(competence) or competence
    normalized_reference = normalize_competence(reference_month) if reference_month else None
    try:
        parsed_entry_date = date.fromisoformat(entry_date)
    except Exception:
        parsed_entry_date = date.today()

    if (kind or "").strip().upper() == "RENDIMENTO" and not normalized_reference:
        normalized_reference = competence

    try:
        create_entry(
            db,
            investment_account_id=investment_account_id,
            competence=competence,
            entry_date=parsed_entry_date,
            kind=kind,
            amount=amount,
            description=description,
            reference_month=normalized_reference,
            notes=notes,
        )
    except ValueError as exc:
        return RedirectResponse(
            _page_url(
                competence=competence,
                account_id=filter_account_id,
                kind=filter_kind,
                q=filter_q,
                months=months,
                error=str(exc),
                anchor="#movimentos",
            ),
            status_code=303,
        )

    return RedirectResponse(
        _page_url(
            competence=competence,
            account_id=filter_account_id,
            kind=filter_kind,
            q=filter_q,
            months=months,
            ok="Movimento salvo com sucesso.",
            anchor="#movimentos",
        ),
        status_code=303,
    )


@router.post("/movimentos/{entry_id}/delete")
def investimentos_delete_entry(
    entry_id: int,
    competence: str = Form(...),
    months: int = Form(6),
    account_id: int | None = Form(None),
    kind: str | None = Form(None),
    q: str | None = Form(None),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = normalize_competence(competence) or competence
    deleted = delete_entry(db, entry_id)
    return RedirectResponse(
        _page_url(
            competence=competence,
            account_id=account_id,
            kind=kind,
            q=q,
            months=months,
            ok="Movimento excluido." if deleted else None,
            error=None if deleted else "Movimento nao encontrado.",
            anchor="#movimentos",
        ),
        status_code=303,
    )


@router.get("/relatorio.csv")
def investimentos_report_csv(
    end: str,
    months: int = 6,
    account_id: int | None = None,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    end = normalize_competence(end) or end
    months = sanitize_report_months(months)
    accounts = list_accounts(db, active_only=False)
    selected_account = next((item for item in accounts if item.id == account_id), None)
    if account_id and not selected_account:
        account_id = None
    report = investment_report(db, end_ym=end, months=months, account_id=account_id)

    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["competence", "aportes", "resgates", "rendimentos", "ajustes", "saldo_final"],
        delimiter=";",
    )
    writer.writeheader()
    for row in report.get("series", []):
        writer.writerow(
            {
                "competence": row.get("competence"),
                "aportes": float(row.get("aportes") or 0.0),
                "resgates": float(row.get("resgates") or 0.0),
                "rendimentos": float(row.get("rendimentos") or 0.0),
                "ajustes": float(row.get("ajustes") or 0.0),
                "saldo_final": float(row.get("saldo") or 0.0),
            }
        )

    filename = "investimentos"
    if selected_account:
        filename += f"_{selected_account.id}"
    filename += f"_{report.get('start')}_{report.get('end')}.csv"
    content = "\ufeff" + output.getvalue()
    return StreamingResponse(
        iter([content.encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/relatorio.pdf")
def investimentos_report_pdf(
    end: str,
    months: int = 6,
    account_id: int | None = None,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    end = normalize_competence(end) or end
    months = sanitize_report_months(months)
    accounts = list_accounts(db, active_only=False)
    selected_account = next((account for account in accounts if account.id == account_id), None)
    if account_id and not selected_account:
        account_id = None
    report = investment_report(db, end_ym=end, months=months, account_id=account_id)
    movements = list_entries(
        db,
        start_ym=report.get("start"),
        end_ym=report.get("end"),
        account_id=account_id,
        limit=200,
    )

    payload = {
        "report": report,
        "account_name": selected_account.name if selected_account else "Todas as contas",
        "accounts_count": report.get("accounts_count", 0),
        "movements": [
            {
                "entry_date": movement.entry_date.strftime("%d/%m/%Y") if movement.entry_date else "-",
                "account_name": movement.account.name if movement.account else "-",
                "kind": movement.kind,
                "kind_label": KIND_LABELS.get(movement.kind, movement.kind.title()),
                "description": movement.description,
                "amount": float(movement.amount or 0.0),
            }
            for movement in movements
        ],
    }
    pdf = investments_report_pdf_bytes(payload)
    filename = f"investimentos_{report.get('start')}_{report.get('end')}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
