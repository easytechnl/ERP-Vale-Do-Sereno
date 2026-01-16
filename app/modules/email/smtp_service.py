import smtplib
from email.message import EmailMessage
from pathlib import Path
from app.core.config import settings

def send_email(to_list: list[str], subject: str, html_body: str, attachments: list[Path] | None = None) -> None:
    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM
    msg["To"] = ", ".join(to_list)
    msg["Subject"] = subject
    msg.set_content("Seu cliente de e-mail não suporta HTML.")
    msg.add_alternative(html_body, subtype="html")

    attachments = attachments or []
    for p in attachments:
        data = p.read_bytes()
        maintype, subtype = "application", "pdf"
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=p.name)

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as smtp:
        if settings.SMTP_TLS:
            smtp.starttls()
        if settings.SMTP_USER:
            smtp.login(settings.SMTP_USER, settings.SMTP_PASS)
        smtp.send_message(msg)
