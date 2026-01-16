from fastapi import APIRouter, Request, Depends, UploadFile, File, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.templating import templates
from app.core.deps import get_db
from app.modules.auth.utils import require_login
from app.modules.conciliacao.service import list_transactions, reconcile_transaction_to_installment
from app.models.receber import Installment
from app.core.storage import competence_dir, write_bytes

router = APIRouter(prefix="/conciliacao", tags=["conciliacao"])

@router.get("")
def conciliacao_page(request: Request, competence: str, user=Depends(require_login), db: Session = Depends(get_db)):
    imports, txns = list_transactions(db, competence)
    installments = db.query(Installment).filter(Installment.competence_month == competence).order_by(Installment.due_date.asc()).all()
    return templates.TemplateResponse("conciliacao/conciliacao.html", {
        "request": request, "user": user, "competence": competence,
        "imports": imports, "txns": txns, "installments": installments,
    })

@router.post("/api/{competence}/upload-csv")
async def upload_csv(competence: str, file: UploadFile = File(...), user=Depends(require_login), db: Session = Depends(get_db)):
    # MVP: apenas salva o arquivo para você plugar o parser depois
    out_dir = competence_dir(competence) / "extratos"
    out_path = out_dir / file.filename
    write_bytes(out_path, await file.read())
    return {"stored_as": str(out_path), "note": "CSV salvo. Parser a implementar em app/modules/conciliacao."}

@router.post("/api/{competence}/conciliar")
def conciliar(
    competence: str,
    bank_txn_id: int = Form(...),
    installment_id: int = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    reconcile_transaction_to_installment(db, bank_txn_id, installment_id)
    return RedirectResponse(f"/conciliacao?competence={competence}", status_code=303)
