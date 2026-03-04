from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.templating import templates
from app.modules.auth.utils import require_login
from app.modules.notas_fiscais.pdf import notas_fiscais_pdf_bytes
from app.models.notas_fiscais import NotaFiscal
from app.models.rateio import RateioCompany


router = APIRouter(prefix="/notas-fiscais", tags=["notas_fiscais"])


def _normalize_view(view: str | None) -> str:
    v = (view or "all").strip().lower()
    mapping = {
        "paid": "paid",
        "paga": "paid",
        "a_vencer": "a_vencer",
        "pending": "a_vencer",
        "due_soon": "a_vencer",
        "vencida": "vencida",
        "overdue": "vencida",
    }
    return mapping.get(v, "all")


def _redirect_back(competence: str, view: str | None = None) -> RedirectResponse:
    v = _normalize_view(view)
    return RedirectResponse(url=f"/notas-fiscais?competence={competence}&view={v}", status_code=303)


def _normalize_status(status: str) -> str:
    st = (status or "").strip().upper()
    mapping = {
        "PAGA": "PAGA",
        "PAGO": "PAGA",
        "A VENCER": "A_VENCER",
        "AVENCER": "A_VENCER",
        "A_VENCER": "A_VENCER",
        "VENCIDA": "VENCIDA",
        "VENCIDO": "VENCIDA",
    }
    return mapping.get(st, "A_VENCER")


@router.get("")
@router.get("/")
def notas_fiscais_page(
    request: Request,
    competence: str | None = None,
    view: str = "all",
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    today = datetime.date.today()
    competence = competence or today.strftime("%Y-%m")

    rows = (
        db.query(NotaFiscal)
        .filter(NotaFiscal.competence_month == competence)
        .order_by(NotaFiscal.id.desc())
        .all()
    )

    companies = (
        db.query(RateioCompany)
        .filter(RateioCompany.active == True)
        .order_by(RateioCompany.name.asc())
        .all()
    )
    companies_ui = [{"id": c.id, "name": c.name} for c in companies]

    notas = []
    for nf in rows:
        due = nf.due_date
        st = _normalize_status(nf.status or "A_VENCER")
        is_paid = st == "PAGA"
        overdue = bool((st == "VENCIDA") or (due and (not is_paid) and (due < today)))
        due_soon = bool(due and (not is_paid) and (not overdue) and (0 <= (due - today).days <= 5))
        notas.append(
            {
                "id": nf.id,
                "numero": nf.numero,
                "fornecedor": nf.fornecedor or "",
                "descricao": nf.descricao or "",
                "competence_month": nf.competence_month,
                "issue_date": nf.issue_date,
                "due_date": nf.due_date,
                "amount": float(nf.amount or 0.0),
                "status": st,
                "paid_at": nf.paid_at,
                "overdue": overdue,
                "due_soon": due_soon,
                "notes": nf.notes or "",
            }
        )

    paid = [x for x in notas if x["status"] == "PAGA"]
    a_vencer = [x for x in notas if x["status"] == "A_VENCER"]
    vencida = [x for x in notas if x["status"] == "VENCIDA"]

    def _sum(items):
        return float(sum(x["amount"] for x in items))

    stats = {
        "all_total": _sum(notas),
        "paid_total": _sum(paid),
        "a_vencer_total": _sum(a_vencer),
        "vencida_total": _sum(vencida),
        "paid_count": len(paid),
        "a_vencer_count": len(a_vencer),
        "vencida_count": len(vencida),
        "all_count": len(notas),
    }

    view = _normalize_view(view)
    if view == "paid":
        visible = paid
    elif view == "a_vencer":
        visible = a_vencer
    elif view == "vencida":
        visible = vencida
    else:
        visible = notas

    return templates.TemplateResponse(
        "notas_fiscais/notas_fiscais.html",
        {
            "request": request,
            "user": user,
            "competence": competence,
            "notas": visible,
            "stats": stats,
            "view": view,
            "companies": companies_ui,
        },
    )


@router.post("/create")
def notas_fiscais_create(
    competence: str = Form(...),
    view: str = Form("all"),
    numero: str = Form(...),
    fornecedor: str = Form(""),
    descricao: str = Form(""),
    issue_date: str = Form(""),
    due_date: str = Form(""),
    amount: float = Form(...),
    status: str = Form("A_VENCER"),
    notes: str = Form(""),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    issue_dt = datetime.date.fromisoformat(issue_date) if issue_date.strip() else None
    due_dt = datetime.date.fromisoformat(due_date) if due_date.strip() else None

    nf = NotaFiscal(
        numero=numero.strip(),
        fornecedor=(fornecedor.strip() or None),
        descricao=(descricao.strip() or None),
        competence_month=competence,
        issue_date=issue_dt,
        due_date=due_dt,
        amount=float(amount),
        status=_normalize_status(status),
        paid_at=(datetime.date.today() if _normalize_status(status) == "PAGA" else None),
        notes=(notes.strip() or None),
    )
    db.add(nf)
    db.commit()
    return _redirect_back(competence, view)


@router.post("/{nf_id}/status")
def notas_fiscais_update_status(
    nf_id: int,
    competence: str = Form(...),
    view: str = Form("all"),
    status: str = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    nf = db.query(NotaFiscal).get(nf_id)
    if nf:
        st = _normalize_status(status)
        nf.status = st
        if st == "PAGA" and nf.paid_at is None:
            nf.paid_at = datetime.date.today()
        if st != "PAGA":
            nf.paid_at = None
        db.commit()
    return _redirect_back(competence, view)


@router.post("/{nf_id}/delete")
def notas_fiscais_delete(
    nf_id: int,
    competence: str = Form(...),
    view: str = Form("all"),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    nf = db.query(NotaFiscal).get(nf_id)
    if nf:
        db.delete(nf)
        db.commit()
    return _redirect_back(competence, view)


@router.get("/export/pdf")
def notas_fiscais_export_pdf(
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(NotaFiscal)
        .order_by(NotaFiscal.competence_month.desc(), NotaFiscal.id.desc())
        .all()
    )
    pdf_bytes = notas_fiscais_pdf_bytes(rows)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"notas_fiscais_{stamp}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
