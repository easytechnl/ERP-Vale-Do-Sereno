from __future__ import annotations

import json
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.email import EmailTemplate, EmailBatch, EmailMessage, EmailReminderLog
from app.models.boletos import Boleto
from app.models.receber import Installment
from app.modules.email.smtp_service import send_email
from app.modules.relatorios.service import latest_demonstrativo


DEFAULT_TEMPLATE_CODE = "BOLETO_MENSAL"
DEFAULT_REMINDER_TEMPLATE_CODE = "BOLETO_PRESTES_A_VENCER"
DEFAULT_REMINDER_DAYS = (10, 5, 3, 1)
PAID_LIKE = {"PAGA", "PAGO", "BAIXADA", "BAIXADO", "CANCELADA", "CANCELADO"}
SETTINGS_PATH = Path("data/configuracoes.json")


def _load_runtime_preferences() -> dict:
    try:
        if SETTINGS_PATH.exists():
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            return (data or {}).get("preferences", {}) or {}
    except Exception:
        pass
    return {}


def is_auto_due_reminder_enabled() -> bool:
    prefs = _load_runtime_preferences()
    return bool(prefs.get("auto_due_reminder_emails", False))


def ensure_default_template(db: Session):
    t = db.query(EmailTemplate).filter(EmailTemplate.code == DEFAULT_TEMPLATE_CODE).first()
    if t:
        return t
    t = EmailTemplate(
        code=DEFAULT_TEMPLATE_CODE,
        subject_tpl="Boleto - Competencia {{competence}} - {{customer_name}}",
        body_tpl_html="""<div style='font-family:Arial,sans-serif'>
        <p>Ola, {{customer_name}}.</p>
        <p>Segue o boleto da competencia <b>{{competence}}</b> no valor de <b>R$ {{amount}}</b> com vencimento em <b>{{due_date}}</b>.</p>
        <p>Atenciosamente,<br/>Financeiro</p>
        </div>""",
        variables_json={"vars": ["customer_name", "competence", "amount", "due_date"]},
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def ensure_default_reminder_template(db: Session):
    t = db.query(EmailTemplate).filter(EmailTemplate.code == DEFAULT_REMINDER_TEMPLATE_CODE).first()
    if t:
        return t
    t = EmailTemplate(
        code=DEFAULT_REMINDER_TEMPLATE_CODE,
        subject_tpl="Lembrete: boleto vence em {{days_left}} dia(s) - {{customer_name}}",
        body_tpl_html="""<div style='font-family:Arial,sans-serif'>
        <p>Ola, {{customer_name}}.</p>
        <p>Este e um lembrete: seu boleto da competencia <b>{{competence}}</b> no valor de <b>R$ {{amount}}</b> vence em <b>{{days_left}} dia(s)</b>.</p>
        <p>Vencimento: <b>{{due_date}}</b>.</p>
        <p>Se o pagamento ja foi realizado, por favor desconsidere esta mensagem.</p>
        <p>Atenciosamente,<br/>Financeiro</p>
        </div>""",
        variables_json={"vars": ["customer_name", "competence", "amount", "due_date", "days_left"]},
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def render_template(subject_tpl: str, body_tpl: str, ctx: dict) -> tuple[str, str]:
    def r(s: str) -> str:
        for k, v in ctx.items():
            s = s.replace("{{" + k + "}}", str(v))
        return s

    return r(subject_tpl), r(body_tpl)


def _is_unpaid_boleto(b: Boleto) -> bool:
    boleto_status = str((b.status or "")).upper()
    inst_status = str((b.installment.status if b.installment else "") or "").upper()
    return boleto_status not in PAID_LIKE and inst_status not in PAID_LIKE


def send_batch_for_competence(db: Session, competence: str, *, only_overdue: bool = False) -> dict:
    today = date.today()
    tmpl = ensure_default_template(db)
    batch = EmailBatch(
        competence_month=competence,
        status="ENVIANDO",
        filters_json={
            "competence": competence,
            "only_overdue": bool(only_overdue),
            "reference_date": today.isoformat(),
        },
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    fechamento = latest_demonstrativo(db, competence)
    fechamento_path = Path(fechamento.pdf_path) if fechamento and fechamento.pdf_path else None

    boletos = (
        db.query(Boleto)
        .join(Installment, Installment.id == Boleto.installment_id)
        .filter(Installment.competence_month == competence)
        .all()
    )

    if only_overdue:
        boletos = [b for b in boletos if b.due_date and b.due_date < today and _is_unpaid_boleto(b)]

    sent = 0
    failed = 0

    for b in boletos:
        inst = db.query(Installment).filter(Installment.id == b.installment_id).first()
        if not inst or not inst.receivable or not inst.receivable.customer:
            continue
        cust = inst.receivable.customer
        if not cust.email:
            continue

        ctx = {
            "customer_name": cust.name,
            "competence": competence,
            "amount": f"{float(b.amount):.2f}",
            "due_date": b.due_date.isoformat(),
        }
        subject, body = render_template(tmpl.subject_tpl, tmpl.body_tpl_html, ctx)

        msg = EmailMessage(
            batch_id=batch.id,
            to_emails=cust.email,
            subject=subject,
            body_html=body,
            status="PENDENTE",
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)

        attachments = []
        if b.pdf_path:
            attachments.append(Path(b.pdf_path))
        if fechamento_path and fechamento_path.exists():
            attachments.append(fechamento_path)

        try:
            send_email([cust.email], subject, body, attachments)
            msg.status = "ENVIADO"
            msg.sent_at = datetime.now(timezone.utc)
            sent += 1
        except Exception as e:
            msg.status = "FALHOU"
            msg.error = str(e)
            failed += 1

        db.commit()

    batch.status = "CONCLUIDO" if failed == 0 else "FALHOU"
    db.commit()
    return {
        "batch_id": batch.id,
        "sent": sent,
        "failed": failed,
        "total": len(boletos),
        "only_overdue": bool(only_overdue),
        "reference_date": today.isoformat(),
    }


def send_due_soon_reminders(db: Session, *, days_before: tuple[int, ...] = DEFAULT_REMINDER_DAYS) -> dict:
    """Envia lembretes automáticos para boletos prestes a vencer (10,5,3,1 dias)."""
    EmailReminderLog.__table__.create(bind=db.get_bind(), checkfirst=True)
    reminder_tpl = ensure_default_reminder_template(db)
    today = date.today()
    min_comp = today.strftime("%Y-%m")

    batch = EmailBatch(
        competence_month=min_comp,
        status="ENVIANDO",
        filters_json={
            "automatic": True,
            "kind": "due_soon_reminder",
            "days_before": list(days_before),
            "reference_date": today.isoformat(),
        },
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    boletos = (
        db.query(Boleto)
        .join(Installment, Installment.id == Boleto.installment_id)
        .all()
    )

    sent = 0
    failed = 0
    candidates = 0

    for b in boletos:
        inst = b.installment
        if not inst or not inst.receivable or not inst.receivable.customer:
            continue
        if not b.due_date or not _is_unpaid_boleto(b):
            continue
        days_left = (b.due_date - today).days
        if days_left not in days_before:
            continue

        cust = inst.receivable.customer
        email = (cust.email or "").strip()
        if not email:
            continue

        already = (
            db.query(EmailReminderLog)
            .filter(
                EmailReminderLog.installment_id == inst.id,
                EmailReminderLog.days_before == days_left,
            )
            .first()
        )
        if already:
            continue

        candidates += 1
        ctx = {
            "customer_name": cust.name,
            "competence": inst.competence_month,
            "amount": f"{float(b.amount):.2f}",
            "due_date": b.due_date.strftime("%d/%m/%Y"),
            "days_left": str(days_left),
        }
        subject, body = render_template(reminder_tpl.subject_tpl, reminder_tpl.body_tpl_html, ctx)
        msg = EmailMessage(
            batch_id=batch.id,
            to_emails=email,
            subject=subject,
            body_html=body,
            status="PENDENTE",
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)

        attachments = []
        if b.pdf_path:
            p = Path(b.pdf_path)
            if p.exists():
                attachments.append(p)

        try:
            send_email([email], subject, body, attachments)
            msg.status = "ENVIADO"
            msg.sent_at = datetime.now(timezone.utc)
            db.add(
                EmailReminderLog(
                    installment_id=inst.id,
                    boleto_id=b.id,
                    customer_email=email,
                    due_date=b.due_date,
                    days_before=days_left,
                )
            )
            sent += 1
        except Exception as e:
            msg.status = "FALHOU"
            msg.error = str(e)
            failed += 1

        db.commit()

    batch.status = "CONCLUIDO" if failed == 0 else "FALHOU"
    db.commit()
    return {
        "batch_id": batch.id,
        "sent": sent,
        "failed": failed,
        "candidates": candidates,
        "days_before": list(days_before),
        "reference_date": today.isoformat(),
    }
