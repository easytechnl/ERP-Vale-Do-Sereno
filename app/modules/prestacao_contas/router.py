from fastapi import APIRouter, Request, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.templating import templates
from app.core.deps import get_db
from app.modules.auth.utils import require_login
from app.modules.prestacao_contas.service import prestacao_contas_data
from app.modules.prestacao_contas.pdf import (
    boletos_previstos_pdf_bytes,
    boletos_status_pdf_bytes,
    prestacao_resumo_pdf_bytes,
)

router = APIRouter(tags=["prestacao_contas"])


@router.get("/prestacao-contas")
def prestacao_contas_page(
    request: Request,
    competence: str,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    data = prestacao_contas_data(db, competence)
    return templates.TemplateResponse(
        "prestacao_contas/index.html",
        {
            "request": request,
            "user": user,
            "competence": competence,
            "data": data,
        },
    )


@router.get("/prestacao-contas/pdf/boletos-previstos")
def prestacao_pdf_boletos_previstos(
    competence: str,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    data = prestacao_contas_data(db, competence)
    payload = {
        "competence": competence,
        "next_competence": (data.get("boletos_pagar_next") or {}).get("competence"),
        "boletos_pagar": data.get("boletos_pagar") or {},
        "boletos_pagar_next": data.get("boletos_pagar_next") or {},
    }
    pdf = boletos_previstos_pdf_bytes(payload)
    filename = f"boletos_previstos_{competence}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"},
    )


@router.get("/prestacao-contas/pdf/boletos-status")
def prestacao_pdf_boletos_status(
    competence: str,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    data = prestacao_contas_data(db, competence)
    payload = {
        "competence": competence,
        "boletos_pagar": data.get("boletos_pagar") or {},
    }
    pdf = boletos_status_pdf_bytes(payload)
    filename = f"boletos_status_{competence}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"},
    )


@router.get("/prestacao-contas/pdf/resumo")
def prestacao_pdf_resumo(
    competence: str,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    data = prestacao_contas_data(db, competence)
    payload = {
        "competence": competence,
        "current": data.get("current") or {},
        "previous": data.get("previous") or {},
        "saldo_var_pct": data.get("saldo_var_pct"),
        "next_competence": (data.get("boletos_pagar_next") or {}).get("competence"),
        "boletos_pagar_next": data.get("boletos_pagar_next") or {},
    }
    pdf = prestacao_resumo_pdf_bytes(payload)
    filename = f"prestacao_resumo_{competence}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"},
    )
