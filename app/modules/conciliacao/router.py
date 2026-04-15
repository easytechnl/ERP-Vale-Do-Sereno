from fastapi import APIRouter, Request, Depends, UploadFile, File, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.templating import templates
from app.core.deps import get_db
from app.core.utils import clamp_competence, current_competence
from app.modules.auth.utils import require_login
from app.modules.conciliacao.service import list_transactions, reconcile_transaction_to_installment, delete_statement_import
from app.models.receber import Installment
from app.core.storage import competence_dir, write_bytes
from app.modules.conciliacao.ofx_service import import_ofx

router = APIRouter(prefix="/conciliacao", tags=["conciliacao"])

@router.get("")
def conciliacao_page(request: Request, competence: str | None = None, user=Depends(require_login), db: Session = Depends(get_db)):
    competence = clamp_competence(competence, fallback=current_competence()) or current_competence()
    imports, txns = list_transactions(db, competence)
    # Mantido por compatibilidade, mas a UI do espelho do extrato não força conciliação por parcela.
    installments = db.query(Installment).filter(Installment.competence_month == competence).order_by(Installment.due_date.asc()).all()
    return templates.TemplateResponse("conciliacao/conciliacao.html", {
        "request": request, "user": user, "competence": competence,
        "imports": imports, "txns": txns, "installments": installments,
    })


@router.post("/api/{competence}/imports/{import_id}/delete")
def delete_import(
    competence: str,
    import_id: int,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    """Exclui um extrato importado (e suas transações) para manter o histórico limpo."""
    competence = clamp_competence(competence) or competence
    delete_statement_import(db, import_id)
    return RedirectResponse(f"/conciliacao?competence={competence}", status_code=303)

@router.post("/api/{competence}/upload-ofx")
async def upload_ofx(
    competence: str,
    file: UploadFile = File(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    """Importa um extrato OFX e gera o histórico (bank_transactions)."""
    competence = clamp_competence(competence) or competence
    filename = (file.filename or "extrato.ofx").strip()
    lower = filename.lower()

    # aceita .ofx e .qfx (alguns bancos exportam QFX, que é OFX)
    if not (lower.endswith(".ofx") or lower.endswith(".qfx")):
        return {"error": "Envie um arquivo .ofx (ou .qfx)."}

    payload = import_ofx(db, competence, filename, await file.read())

    # Se veio de um <form>, é melhor redirecionar para mostrar as transações.
    # (mantém também um retorno JSON útil caso você chame via fetch)
    return RedirectResponse(f"/conciliacao?competence={competence}", status_code=303)


@router.post("/api/{competence}/upload-csv")
async def upload_csv(competence: str, file: UploadFile = File(...), user=Depends(require_login), db: Session = Depends(get_db)):
    """Compatibilidade: caso enviem OFX aqui por engano, tenta importar; CSV segue como stub."""
    competence = clamp_competence(competence) or competence
    filename = (file.filename or "").strip()
    lower = filename.lower()
    content = await file.read()

    if lower.endswith(".ofx") or lower.endswith(".qfx"):
        import_ofx(db, competence, filename, content)
        return RedirectResponse(f"/conciliacao?competence={competence}", status_code=303)

    # CSV (ainda stub): apenas salva
    out_dir = competence_dir(competence) / "extratos"
    out_path = out_dir / filename
    write_bytes(out_path, content)
    return {"stored_as": str(out_path), "note": "CSV salvo. (Importação CSV ainda não implementada)"}

@router.post("/api/{competence}/conciliar")
def conciliar(
    competence: str,
    bank_txn_id: int = Form(...),
    installment_id: int = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = clamp_competence(competence) or competence
    reconcile_transaction_to_installment(db, bank_txn_id, installment_id)
    return RedirectResponse(f"/conciliacao?competence={competence}", status_code=303)
