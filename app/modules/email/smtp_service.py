import json
import smtplib
from email.message import EmailMessage
from pathlib import Path

from app.core.config import settings

SETTINGS_PATH = Path("data/configuracoes.json")


def _load_email_overrides() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    val = data.get("email") or {}
    return val if isinstance(val, dict) else {}


def _bool(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def send_email(to_list: list[str], subject: str, html_body: str, attachments: list[Path] | None = None) -> None:
    overrides = _load_email_overrides()
    smtp_host = (overrides.get("smtp_host") or settings.SMTP_HOST).strip()
    smtp_user = (overrides.get("smtp_user") or settings.SMTP_USER).strip()
    smtp_pass = overrides.get("smtp_pass") or settings.SMTP_PASS
    smtp_from = (overrides.get("smtp_from") or settings.SMTP_FROM).strip() or settings.SMTP_FROM
    smtp_port = overrides.get("smtp_port") or settings.SMTP_PORT
    try:
        smtp_port = int(smtp_port)
    except Exception:
        smtp_port = settings.SMTP_PORT
    smtp_tls = _bool(overrides.get("smtp_tls"))
    if smtp_tls is None:
        smtp_tls = settings.SMTP_TLS

    msg = EmailMessage()
    msg["From"] = smtp_from
    msg["To"] = ", ".join(to_list)
    msg["Subject"] = subject
    msg.set_content("Seu cliente de e-mail nao suporta HTML.")
    msg.add_alternative(html_body, subtype="html")

    attachments = attachments or []
    for p in attachments:
        data = p.read_bytes()
        maintype, subtype = "application", "pdf"
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=p.name)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
        if smtp_tls:
            smtp.starttls()
        if smtp_user:
            smtp.login(smtp_user, smtp_pass)
        smtp.send_message(msg)
