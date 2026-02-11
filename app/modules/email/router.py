from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.templating import templates
from app.core.deps import get_db
from app.modules.auth.utils import require_login
from app.modules.email.service import send_batch_for_competence, send_due_soon_reminders
from app.models.email import EmailBatch, EmailMessage
from app.models.rateio import RateioCompany


router = APIRouter(prefix="/email", tags=["email"])
SETTINGS_PATH = Path("data/configuracoes.json")


def _load_company_emails() -> dict[str, str]:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    val = data.get("company_emails") or {}
    return val if isinstance(val, dict) else {}


def _save_company_email(company_id: int, email: str | None) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}
    company_emails = data.get("company_emails") or {}
    key = str(company_id)
    if email:
        company_emails[key] = email
    else:
        company_emails.pop(key, None)
    data["company_emails"] = company_emails
    SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@router.get("/lote")
def email_lote_page(
    request: Request,
    competence: str,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    batches = db.query(EmailBatch).filter(EmailBatch.competence_month == competence).order_by(EmailBatch.id.desc()).all()
    messages = []
    if batches:
        messages = db.query(EmailMessage).filter(EmailMessage.batch_id == batches[0].id).order_by(EmailMessage.id.desc()).limit(50).all()

    company_emails = _load_company_emails()
    companies = (
        db.query(RateioCompany)
        .filter(RateioCompany.active == True)
        .order_by(RateioCompany.name.asc())
        .all()
    )
    companies_ui = [{"id": c.id, "name": c.name, "email": (company_emails.get(str(c.id)) or "")} for c in companies]

    return templates.TemplateResponse(
        "email/lote.html",
        {
            "request": request,
            "user": user,
            "competence": competence,
            "batches": batches,
            "messages": messages,
            "companies": companies_ui,
        },
    )


@router.post("/api/{competence}/enviar-lote")
def api_enviar_lote(competence: str, user=Depends(require_login), db: Session = Depends(get_db)):
    # Por padrão, o lote da tela envia apenas para clientes em atraso.
    return send_batch_for_competence(db, competence, only_overdue=True)


@router.post("/api/reminders/run-now")
def api_run_due_reminders_now(user=Depends(require_login), db: Session = Depends(get_db)):
    return send_due_soon_reminders(db)


@router.post("/construtoras/{company_id}/email")
def update_construtora_email(
    company_id: int,
    competence: str = Form(...),
    email: str = Form(""),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    company = db.query(RateioCompany).filter(RateioCompany.id == company_id).first()
    if company:
        _save_company_email(company_id, (email or "").strip())
    return RedirectResponse(url=f"/email/lote?competence={competence}", status_code=303)
