from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session

from app.core.templating import templates
from app.core.deps import get_db
from app.modules.auth.utils import require_login
from app.modules.email.service import send_batch_for_competence
from app.models.email import EmailBatch, EmailMessage

router = APIRouter(prefix="/email", tags=["email"])

@router.get("/lote")
def email_lote_page(request: Request, competence: str, user=Depends(require_login), db: Session = Depends(get_db)):
    batches = db.query(EmailBatch).filter(EmailBatch.competence_month == competence).order_by(EmailBatch.id.desc()).all()
    messages = []
    if batches:
        messages = db.query(EmailMessage).filter(EmailMessage.batch_id == batches[0].id).order_by(EmailMessage.id.desc()).limit(50).all()
    return templates.TemplateResponse("email/lote.html", {"request": request, "user": user, "competence": competence, "batches": batches, "messages": messages})

@router.post("/api/{competence}/enviar-lote")
def api_enviar_lote(competence: str, user=Depends(require_login), db: Session = Depends(get_db)):
    return send_batch_for_competence(db, competence)
