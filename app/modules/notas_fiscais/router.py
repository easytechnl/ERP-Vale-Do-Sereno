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


def _redirect_back(competence: str) -> RedirectResponse:
    return RedirectResponse(url=f"/notas-fiscais?competence={competence}", status_code=303)


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
        st = (nf.status or "A_VENCER").upper()
        is_paid = st == "PAGA"
        overdue = bool(due and (not is_paid) and (due < today))
        due_soon = bool(due and (not is_paid) and (0 <= (due - today).days <= 5))
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
    pending = [x for x in notas if x["status"] != "PAGA"]
    overdue = [x for x in pending if x["overdue"]]
    due_soon = [x for x in pending if x["due_soon"]]

    def _sum(items):
        return float(sum(x["amount"] for x in items))

    stats = {
        "paid_total": _sum(paid),
        "pending_total": _sum(pending),
        "overdue_total": _sum(overdue),
        "due_soon_total": _sum(due_soon),
        "paid_count": len(paid),
        "pending_count": len(pending),
        "overdue_count": len(overdue),
        "due_soon_count": len(due_soon),
        "all_count": len(notas),
    }

    view = (view or "all").lower()
    if view == "paid":
        visible = paid
    elif view == "pending":
        visible = pending
    elif view == "overdue":
        visible = overdue
    elif view == "due_soon":
        visible = due_soon
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
    return _redirect_back(competence)


@router.post("/{nf_id}/status")
def notas_fiscais_update_status(
    nf_id: int,
    competence: str = Form(...),
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
    return _redirect_back(competence)


@router.post("/{nf_id}/delete")
def notas_fiscais_delete(
    nf_id: int,
    competence: str = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    nf = db.query(NotaFiscal).get(nf_id)
    if nf:
        db.delete(nf)
        db.commit()
    return _redirect_back(competence)


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
