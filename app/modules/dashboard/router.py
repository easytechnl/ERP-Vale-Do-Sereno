from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session

from app.core.templating import templates
from app.core.deps import get_db
from app.modules.auth.utils import require_login
from app.modules.relatorios.service import get_or_create_monthly_close
from app.modules.lancamentos.service import totals_for_period

router = APIRouter()

@router.get("/")
def home(request: Request, user=Depends(require_login), db: Session = Depends(get_db)):
    # competência padrão: mês atual
    import datetime
    competence = datetime.date.today().strftime("%Y-%m")
    close = get_or_create_monthly_close(db, competence)
    totals = totals_for_period(db, start_ym=competence, end_ym=competence)
    return templates.TemplateResponse("dashboard/home.html", {
        "request": request,
        "user": user,
        "competence": competence,
        "close": close,
        "totals": totals,
    })
