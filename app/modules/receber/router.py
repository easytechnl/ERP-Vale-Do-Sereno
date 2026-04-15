from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session

from app.core.templating import templates
from app.core.deps import get_db
from app.core.utils import clamp_competence, current_competence
from app.modules.auth.utils import require_login
from app.models.receber import Installment
from app.modules.receber.service import generate_installments_for_competence, seed_receivables_if_empty

router = APIRouter(prefix="/receber", tags=["receber"])

@router.get("")
def receber_page(request: Request, competence: str | None = None, user=Depends(require_login), db: Session = Depends(get_db)):
    competence = clamp_competence(competence, fallback=current_competence()) or current_competence()
    seed_receivables_if_empty(db)
    itens = db.query(Installment).filter(Installment.competence_month == competence).order_by(Installment.due_date.asc()).all()
    return templates.TemplateResponse("receber/receber.html", {"request": request, "user": user, "competence": competence, "itens": itens})

@router.post("/api/{competence}/gerar-parcelas")
def api_gerar_parcelas(competence: str, user=Depends(require_login), db: Session = Depends(get_db)):
    competence = clamp_competence(competence) or competence
    return generate_installments_for_competence(db, competence, day=10)
