from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.orm import Session

from app.models.email import EmailTemplate, EmailBatch, EmailMessage, EmailAttachment
from app.models.boletos import Boleto
from app.models.receber import Installment
from app.modules.email.smtp_service import send_email
from app.modules.relatorios.service import latest_demonstrativo

DEFAULT_TEMPLATE_CODE = "BOLETO_MENSAL"

def ensure_default_template(db: Session):
    t = db.query(EmailTemplate).filter(EmailTemplate.code == DEFAULT_TEMPLATE_CODE).first()
    if t:
        return t
    t = EmailTemplate(
        code=DEFAULT_TEMPLATE_CODE,
        subject_tpl="Boleto — Competência {{competence}} — {{customer_name}}",
        body_tpl_html="""<div style='font-family:Arial,sans-serif'>
        <p>Olá, {{customer_name}}.</p>
        <p>Segue o boleto da competência <b>{{competence}}</b> no valor de <b>R$ {{amount}}</b> com vencimento em <b>{{due_date}}</b>.</p>
        <p>Atenciosamente,<br/>Financeiro</p>
        </div>""",
        variables_json={"vars": ["customer_name", "competence", "amount", "due_date"]},
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t

def render_template(subject_tpl: str, body_tpl: str, ctx: dict) -> tuple[str, str]:
    # render simples (sem engine): substitui {{var}} por valor
    def r(s: str) -> str:
        for k, v in ctx.items():
            s = s.replace("{{" + k + "}}", str(v))
        return s
    return r(subject_tpl), r(body_tpl)

def send_batch_for_competence(db: Session, competence: str) -> dict:
    tmpl = ensure_default_template(db)
    batch = EmailBatch(competence_month=competence, status="ENVIANDO", filters_json={"competence": competence})
    db.add(batch)
    db.commit()
    db.refresh(batch)

    # anexos padrão: fechamento da competência (se existir)
    fechamento = latest_demonstrativo(db, competence)
    fechamento_path = Path(fechamento.pdf_path) if fechamento and fechamento.pdf_path else None

    boletos = (
        db.query(Boleto)
        .join(Installment, Installment.id == Boleto.installment_id)
        .filter(Installment.competence_month == competence)
        .all()
    )

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
    return {"batch_id": batch.id, "sent": sent, "failed": failed, "total": len(boletos)}
