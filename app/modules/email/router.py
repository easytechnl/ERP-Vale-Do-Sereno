from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.templating import templates
from app.core.deps import get_db
from app.modules.auth.utils import require_login, require_role
from app.modules.email.smtp_service import send_email
from app.modules.email.service import (
    send_batch_for_competence,
    send_due_soon_reminders,
    list_due_soon_candidates,
    send_due_soon_reminders_for_boleto_ids,
    send_due_soon_manual_reminders_for_ids,
)
from app.models.email import EmailBatch, EmailMessage
from app.models.rateio import RateioCompany


router = APIRouter(prefix="/email", tags=["email"])
SETTINGS_PATH = Path("data/configuracoes.json")


def _load_settings_data() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save_settings_data(data: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_company_emails() -> dict[str, str]:
    data = _load_settings_data()
    val = data.get("company_emails") or {}
    return val if isinstance(val, dict) else {}


def _save_company_email(company_id: int, email: str | None) -> None:
    data = _load_settings_data()
    company_emails = data.get("company_emails") or {}
    key = str(company_id)
    if email:
        company_emails[key] = email
    else:
        company_emails.pop(key, None)
    data["company_emails"] = company_emails
    _save_settings_data(data)


def _is_auto_due_reminder_enabled() -> bool:
    data = _load_settings_data()
    prefs = data.get("preferences") or {}
    if not isinstance(prefs, dict):
        return False
    return bool(prefs.get("auto_due_reminder_emails", False))


def _save_auto_due_reminder_enabled(enabled: bool) -> None:
    data = _load_settings_data()
    prefs = data.get("preferences") or {}
    if not isinstance(prefs, dict):
        prefs = {}
    prefs["auto_due_reminder_emails"] = bool(enabled)
    data["preferences"] = prefs
    _save_settings_data(data)


def _coerce_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _load_email_settings_for_ui() -> dict:
    data = _load_settings_data()
    email_cfg = data.get("email") or {}
    if not isinstance(email_cfg, dict):
        email_cfg = {}

    smtp_host = (email_cfg.get("smtp_host") or settings.SMTP_HOST).strip()
    smtp_user = (email_cfg.get("smtp_user") or settings.SMTP_USER).strip()
    smtp_from = (email_cfg.get("smtp_from") or settings.SMTP_FROM).strip() or settings.SMTP_FROM
    smtp_port = email_cfg.get("smtp_port")
    if smtp_port in (None, ""):
        smtp_port = settings.SMTP_PORT
    smtp_tls = _coerce_bool(email_cfg.get("smtp_tls"), default=bool(settings.SMTP_TLS))

    return {
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "smtp_user": smtp_user,
        "smtp_from": smtp_from,
        "smtp_tls": smtp_tls,
    }


def _is_reasonable_email(value: str) -> bool:
    v = (value or "").strip()
    if "@" not in v:
        return False
    local, _, domain = v.rpartition("@")
    if not local or not domain:
        return False
    if "." not in domain:
        return False
    if domain.startswith(".") or domain.endswith("."):
        return False
    return True


def _email_logo_inline() -> tuple[str, list[tuple[Path, str]]]:
    cid = "arcvstudo_logo"
    candidates = [
        Path("arcvstudo.png"),
        Path("arcvsctudo.png"),
        Path("ARCVSVERDE.png"),
        Path("arc.png"),
    ]
    for p in candidates:
        if p.exists():
            html = (
                "<div style='margin:0 0 16px 0'>"
                f"<img src='cid:{cid}' alt='Vale do Sereno' style='max-width:220px;height:auto;display:block' />"
                "</div>"
            )
            return html, [(p, cid)]
    return "", []


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
    due_soon = list_due_soon_candidates(db)
    due_soon_competences = sorted({str(row.get("competence") or "") for row in due_soon if row.get("competence")})

    return templates.TemplateResponse(
        "email/lote.html",
        {
            "request": request,
            "user": user,
            "competence": competence,
            "batches": batches,
            "messages": messages,
            "companies": companies_ui,
            "due_soon": due_soon,
            "due_soon_competences": due_soon_competences,
            "auto_due_reminder_emails": _is_auto_due_reminder_enabled(),
            "reminder_interval_minutes": max(int(getattr(settings, "EMAIL_REMINDER_INTERVAL_MINUTES", 60)), 5),
            "email_settings": _load_email_settings_for_ui(),
        },
    )


@router.post("/api/{competence}/enviar-lote")
def api_enviar_lote(competence: str, user=Depends(require_login), db: Session = Depends(get_db)):
    # Por padrão, o lote da tela envia apenas para clientes em atraso.
    return send_batch_for_competence(db, competence, only_overdue=True)


@router.post("/api/reminders/run-now")
def api_run_due_reminders_now(user=Depends(require_login), db: Session = Depends(get_db)):
    return send_due_soon_reminders(db)


@router.post("/reminders/send-selected")
def send_due_reminders_selected(
    competence: str = Form(...),
    boleto_ids: list[int] = Form([]),
    manual_ids: list[int] = Form([]),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    result_std = send_due_soon_reminders_for_boleto_ids(db, boleto_ids=boleto_ids)
    result_manual = send_due_soon_manual_reminders_for_ids(db, manual_ids=manual_ids)

    sent_total = int(result_std.get("sent", 0)) + int(result_manual.get("sent", 0))
    failed_total = int(result_std.get("failed", 0)) + int(result_manual.get("failed", 0))
    skipped_total = int(result_std.get("skipped", 0)) + int(result_manual.get("skipped", 0))
    reasons = (result_std.get("skip_reasons") or []) + (result_manual.get("skip_reasons") or [])

    if sent_total > 0 and failed_total == 0:
        msg = quote_plus(
            f"Lembretes enviados com sucesso: enviados={sent_total}, pulados={skipped_total}."
        )
        return RedirectResponse(
            url=f"/email/lote?competence={competence}&due_reminder=ok&due_msg={msg}",
            status_code=303,
        )

    if sent_total > 0 and failed_total > 0:
        msg = quote_plus(
            f"Envio parcial: enviados={sent_total}, falhas={failed_total}, pulados={skipped_total}."
        )
        return RedirectResponse(
            url=f"/email/lote?competence={competence}&due_reminder=warn&due_msg={msg}",
            status_code=303,
        )

    reason = reasons or ["Nenhum boleto elegivel para envio."]
    msg = quote_plus(reason[0])
    return RedirectResponse(
        url=f"/email/lote?competence={competence}&due_reminder=err&due_msg={msg}",
        status_code=303,
    )


@router.post("/reminders/{boleto_id}/send")
def send_due_reminder_single(
    boleto_id: int,
    competence: str = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    result = send_due_soon_reminders_for_boleto_ids(db, boleto_ids=[boleto_id])
    if result["sent"] == 1 and result["failed"] == 0:
        msg = quote_plus("Lembrete enviado com sucesso.")
        return RedirectResponse(
            url=f"/email/lote?competence={competence}&due_reminder=ok&due_msg={msg}",
            status_code=303,
        )

    reason = result.get("skip_reasons") or ["Nao foi possivel enviar o lembrete."]
    msg = quote_plus(reason[0])
    return RedirectResponse(
        url=f"/email/lote?competence={competence}&due_reminder=err&due_msg={msg}",
        status_code=303,
    )


@router.post("/reminders/manual/{manual_id}/send")
def send_due_reminder_single_manual(
    manual_id: int,
    competence: str = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    result = send_due_soon_manual_reminders_for_ids(db, manual_ids=[manual_id])
    if result["sent"] == 1 and result["failed"] == 0:
        msg = quote_plus("Lembrete enviado com sucesso.")
        return RedirectResponse(
            url=f"/email/lote?competence={competence}&due_reminder=ok&due_msg={msg}",
            status_code=303,
        )

    reason = result.get("skip_reasons") or ["Nao foi possivel enviar o lembrete."]
    msg = quote_plus(reason[0])
    return RedirectResponse(
        url=f"/email/lote?competence={competence}&due_reminder=err&due_msg={msg}",
        status_code=303,
    )


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


@router.post("/automation/preferences")
def update_email_automation_preferences(
    competence: str = Form(...),
    auto_due_reminder_emails: str | None = Form(None),
    user=Depends(require_login),
):
    _save_auto_due_reminder_enabled(bool(auto_due_reminder_emails))
    return RedirectResponse(url=f"/email/lote?competence={competence}", status_code=303)


@router.post("/smtp")
def update_email_smtp_settings(
    competence: str = Form(...),
    smtp_host: str = Form(""),
    smtp_port: str = Form(""),
    smtp_user: str = Form(""),
    smtp_pass: str = Form(""),
    smtp_from: str = Form(""),
    smtp_tls: str | None = Form(None),
    user=Depends(require_role("admin")),
):
    data = _load_settings_data()
    email_cfg = data.get("email") or {}
    if not isinstance(email_cfg, dict):
        email_cfg = {}

    host = (smtp_host or "").strip()
    port_raw = (smtp_port or "").strip()
    user_val = (smtp_user or "").strip()
    from_val = (smtp_from or "").strip()

    email_cfg["smtp_host"] = host
    email_cfg["smtp_user"] = user_val
    email_cfg["smtp_from"] = from_val

    if port_raw:
        try:
            email_cfg["smtp_port"] = int(port_raw)
        except ValueError:
            email_cfg["smtp_port"] = port_raw
    else:
        email_cfg["smtp_port"] = ""

    if smtp_pass.strip():
        email_cfg["smtp_pass"] = smtp_pass.strip()

    email_cfg["smtp_tls"] = bool(smtp_tls)

    data["email"] = email_cfg
    _save_settings_data(data)
    return RedirectResponse(url=f"/email/lote?competence={competence}&smtp=ok", status_code=303)


@router.post("/smtp/test")
def send_test_email(
    competence: str = Form(...),
    to_email: str = Form(""),
    user=Depends(require_role("admin")),
):
    target = (to_email or "").strip()
    logo_html, inline_images = _email_logo_inline()
    if not target:
        return RedirectResponse(
            url=f"/email/lote?competence={competence}&smtp_test=err&smtp_test_msg={quote_plus('Informe um e-mail destino.')}",
            status_code=303,
        )
    if not _is_reasonable_email(target):
        return RedirectResponse(
            url=f"/email/lote?competence={competence}&smtp_test=err&smtp_test_msg={quote_plus('Use um e-mail valido (ex: nome@dominio.com).')}",
            status_code=303,
        )

    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    subject = "Teste SMTP - ERP Vale do Sereno"
    body = (
        "<div style='font-family:Arial,sans-serif'>"
        f"{logo_html}"
        "<p>Este e um e-mail de teste do ERP Vale do Sereno.</p>"
        f"<p>Data/hora do teste: <b>{timestamp}</b>.</p>"
        "<p>Se voce recebeu esta mensagem, o SMTP esta funcionando.</p>"
        "</div>"
    )

    try:
        send_email([target], subject, body, [], inline_images=inline_images)
    except Exception as exc:
        msg = quote_plus(str(exc)[:220] or "Falha ao enviar e-mail de teste.")
        return RedirectResponse(
            url=f"/email/lote?competence={competence}&smtp_test=err&smtp_test_msg={msg}",
            status_code=303,
        )

    return RedirectResponse(url=f"/email/lote?competence={competence}&smtp_test=ok", status_code=303)
