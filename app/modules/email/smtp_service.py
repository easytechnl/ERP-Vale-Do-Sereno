import json
import mimetypes
import smtplib
import socket
from email.message import EmailMessage
from pathlib import Path

from app.core.config import settings

SETTINGS_PATH = Path("data/configuracoes.json")


class SMTPValidationError(RuntimeError):
    pass


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


def _guess_mime(path: Path, default: tuple[str, str] = ("application", "octet-stream")) -> tuple[str, str]:
    mime, _ = mimetypes.guess_type(path.name)
    if mime and "/" in mime:
        mt, st = mime.split("/", 1)
        return mt, st
    return default


def _resolve_smtp_settings() -> dict:
    overrides = _load_email_overrides()
    smtp_host = (overrides.get("smtp_host") or settings.SMTP_HOST).strip()
    smtp_user = (overrides.get("smtp_user") or settings.SMTP_USER).strip()
    smtp_pass = overrides.get("smtp_pass") or settings.SMTP_PASS
    smtp_from = (overrides.get("smtp_from") or settings.SMTP_FROM).strip() or settings.SMTP_FROM
    smtp_port = overrides.get("smtp_port") or settings.SMTP_PORT
    try:
        smtp_port = int(smtp_port)
    except Exception as exc:
        raise SMTPValidationError("Porta SMTP invalida.") from exc

    smtp_tls = _bool(overrides.get("smtp_tls"))
    if smtp_tls is None:
        smtp_tls = settings.SMTP_TLS

    if not smtp_host:
        raise SMTPValidationError("Servidor SMTP nao configurado.")
    if smtp_port <= 0:
        raise SMTPValidationError("Porta SMTP invalida.")
    if not smtp_from:
        raise SMTPValidationError("Remetente SMTP nao configurado.")

    return {
        "smtp_host": smtp_host,
        "smtp_user": smtp_user,
        "smtp_pass": smtp_pass,
        "smtp_from": smtp_from,
        "smtp_port": smtp_port,
        "smtp_tls": bool(smtp_tls),
    }


def _friendly_smtp_error(exc: Exception) -> str:
    if isinstance(exc, SMTPValidationError):
        return str(exc)
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "Falha na autenticacao SMTP. Verifique usuario e senha."
    if isinstance(exc, smtplib.SMTPConnectError):
        return "Nao foi possivel conectar ao servidor SMTP."
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return "O servidor SMTP encerrou a conexao durante o envio."
    if isinstance(exc, socket.timeout):
        return "Tempo esgotado ao conectar ao servidor SMTP."
    if isinstance(exc, TimeoutError):
        return "Tempo esgotado ao conectar ao servidor SMTP."
    if isinstance(exc, OSError):
        detail = str(exc).strip()
        return f"Nao foi possivel conectar ao servidor SMTP. {detail}".strip()
    if isinstance(exc, smtplib.SMTPException):
        detail = str(exc).strip()
        return detail or "Falha ao enviar e-mail pelo SMTP."
    detail = str(exc).strip()
    return detail or "Falha ao enviar e-mail pelo SMTP."


def send_email(
    to_list: list[str],
    subject: str,
    html_body: str,
    attachments: list[Path] | None = None,
    inline_images: list[tuple[Path, str]] | None = None,
) -> None:
    cfg = _resolve_smtp_settings()

    msg = EmailMessage()
    msg["From"] = cfg["smtp_from"]
    msg["To"] = ", ".join(to_list)
    msg["Subject"] = subject
    msg.set_content("Seu cliente de e-mail nao suporta HTML.")
    msg.add_alternative(html_body, subtype="html")

    html_part = msg.get_payload()[-1]
    for item in (inline_images or []):
        p, cid = item
        if not p or not p.exists() or not cid:
            continue
        data = p.read_bytes()
        maintype, subtype = _guess_mime(p, default=("image", "png"))
        html_part.add_related(data, maintype=maintype, subtype=subtype, cid=f"<{cid}>", filename=p.name)

    attachments = attachments or []
    for p in attachments:
        data = p.read_bytes()
        maintype, subtype = _guess_mime(p, default=("application", "octet-stream"))
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=p.name)

    try:
        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=30) as smtp:
            smtp.ehlo()
            if cfg["smtp_tls"]:
                smtp.starttls()
                smtp.ehlo()
            if cfg["smtp_user"]:
                smtp.login(cfg["smtp_user"], cfg["smtp_pass"])
            smtp.send_message(msg)
    except Exception as exc:
        raise RuntimeError(_friendly_smtp_error(exc)) from exc
