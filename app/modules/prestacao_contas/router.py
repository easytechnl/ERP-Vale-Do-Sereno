from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session

from app.core.templating import templates
from app.core.deps import get_db
from app.modules.auth.utils import require_login
from app.modules.prestacao_contas.service import prestacao_contas_data

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
