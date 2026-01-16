from fastapi import APIRouter, Request, Depends
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.templating import templates
from app.core.deps import get_db
from app.modules.auth.utils import require_login
from app.modules.relatorios.service import close_month, latest_demonstrativo, get_or_create_monthly_close, periodo_report, generate_periodo_pdf_snapshot

router = APIRouter(prefix="/relatorios", tags=["relatorios"])

@router.get("/fechamento")
def fechamento_page(request: Request, competence: str, user=Depends(require_login), db: Session = Depends(get_db)):
    close = get_or_create_monthly_close(db, competence)
    snap = latest_demonstrativo(db, competence)
    return templates.TemplateResponse("relatorios/fechamento.html", {"request": request, "user": user, "competence": competence, "close": close, "snap": snap})

@router.post("/api/{competence}/fechar")
def api_fechar(competence: str, user=Depends(require_login), db: Session = Depends(get_db)):
    res = close_month(db, competence)
    return res

@router.get("/fechamento/pdf")
def download_fechamento_pdf(competence: str, user=Depends(require_login), db: Session = Depends(get_db)):
    snap = latest_demonstrativo(db, competence)
    if not snap or not snap.pdf_path:
        return {"error": "Fechamento não gerado"}
    return FileResponse(path=snap.pdf_path, filename=f"demonstrativo_{competence}.pdf", media_type="application/pdf")


@router.get("/periodo")
def periodo_page(
    request: Request,
    end: str,
    months: int = 6,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    data = periodo_report(db, end_ym=end, months=months)
    return templates.TemplateResponse(
        "relatorios/periodo.html",
        {"request": request, "user": user, "competence": end, "data": data},
    )


@router.get("/periodo/pdf")
def periodo_pdf(end: str, months: int = 6, user=Depends(require_login), db: Session = Depends(get_db)):
    path = generate_periodo_pdf_snapshot(db, end_ym=end, months=months)
    fname = f"relatorio_periodo_{end}_{months}m.pdf"
    return FileResponse(path=path, filename=fname, media_type="application/pdf")
