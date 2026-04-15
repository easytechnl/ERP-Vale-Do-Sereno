from __future__ import annotations

import json
import unicodedata
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.storage import competence_dir, write_bytes
from app.models.email import EmailTemplate, EmailBatch, EmailMessage, EmailReminderLog, EmailAttachment
from app.models.boletos import Boleto
from app.models.boletos_receber import BoletoAReceber
from app.models.receber import Installment
from app.modules.email.smtp_service import send_email
from app.modules.relatorios.service import latest_demonstrativo
from app.modules.rateio.service import compute_divisao_custos, compute_company_breakdown
from app.modules.rateio.pdf import generate_company_cost_division_pdf_bytes


DEFAULT_TEMPLATE_CODE = "BOLETO_MENSAL"
DEFAULT_REMINDER_TEMPLATE_CODE = "BOLETO_PRESTES_A_VENCER"
DEFAULT_REMINDER_DAYS = (10, 5, 3, 1)
PAID_LIKE = {"PAGA", "PAGO", "BAIXADA", "BAIXADO", "CANCELADA", "CANCELADO"}
SETTINGS_PATH = Path("data/configuracoes.json")
EXTERNAL_COMPANY_ATTACHMENTS_KEY = "company_external_attachments"
OLD_DEFAULT_SUBJECT = "Boleto - Competencia {{competence}} - {{customer_name}}"
OLD_DEFAULT_REMINDER_SUBJECT = "Lembrete: boleto vence em {{days_left}} dia(s) - {{customer_name}}"
EMAIL_LOGO_CID = "arcvstudo_logo"
LEGACY_PRO_DEFAULT_SUBJECT = "Cobranca de boleto - Competencia {{competence}} - {{customer_name}}"
LEGACY_PRO_REMINDER_SUBJECT = "Lembrete de vencimento - {{customer_name}} (vence em {{days_left}} dia(s))"
PRO_TEMPLATE_MARKER = "data-email-theme='vs-corp-v5'"

PRO_DEFAULT_SUBJECT = "Aviso financeiro | Boleto da competencia {{competence}} | Vale do Sereno"
PRO_DEFAULT_BODY = """<div data-email-theme='vs-corp-v5' style='margin:0;padding:28px 12px;background:#ecfdf5;font-family:Arial,sans-serif;color:#0f172a'>
  <table role='presentation' cellspacing='0' cellpadding='0' style='width:100%;max-width:700px;margin:0 auto;background:#ffffff;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden'>
    <tr>
      <td style='height:6px;background:linear-gradient(90deg,#065f46 0%,#10b981 100%)'></td>
    </tr>
    <tr>
      <td style='padding:26px 30px 10px'>
        {{logo_html}}
        <div style='font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:#475569;font-weight:700'>Comunicado Financeiro</div>
        <h1 style='margin:10px 0 6px;font-size:24px;line-height:1.25;color:#0f172a'>Aviso de cobranca de boleto</h1>
        <p style='margin:0;color:#334155;font-size:15px;line-height:1.65'>
          Prezado(a) <b>{{customer_name}}</b>, encaminhamos abaixo os dados do boleto referente a competencia <b>{{competence}}</b>.
        </p>
      </td>
    </tr>
    <tr>
      <td style='padding:10px 30px 0'>
        <table role='presentation' cellspacing='0' cellpadding='0' style='width:100%;border:1px solid #e2e8f0;border-radius:12px;background:#f8fafc'>
          <tr>
            <td style='padding:14px 16px;border-bottom:1px solid #e2e8f0;width:40%;font-size:13px;color:#475569;font-weight:700'>Valor</td>
            <td style='padding:14px 16px;border-bottom:1px solid #e2e8f0;font-size:15px;color:#0f172a;font-weight:700'>R$ {{amount}}</td>
          </tr>
          <tr>
            <td style='padding:14px 16px;width:40%;font-size:13px;color:#475569;font-weight:700'>Vencimento</td>
            <td style='padding:14px 16px;font-size:15px;color:#0f172a;font-weight:700'>{{due_date}}</td>
          </tr>
        </table>
      </td>
    </tr>
    <tr>
      <td style='padding:16px 30px 0'>
        <table role='presentation' cellspacing='0' cellpadding='0' style='width:100%'>
          <tr>
            <td style='padding:0 6px 0 0'>
              <a href='mailto:{{support_email}}?subject=Duvida%20sobre%20boleto%20{{competence}}' style='display:block;text-align:center;text-decoration:none;background:#065f46;color:#ffffff;font-size:13px;font-weight:700;padding:11px 12px;border-radius:10px'>Falar com o Financeiro</a>
            </td>
            <td style='padding:0 0 0 6px'>
              <a href='mailto:{{support_email}}?subject=Comprovante%20de%20pagamento%20{{competence}}' style='display:block;text-align:center;text-decoration:none;background:#d1fae5;color:#065f46;font-size:13px;font-weight:700;padding:11px 12px;border-radius:10px'>Enviar comprovante</a>
            </td>
          </tr>
        </table>
      </td>
    </tr>
    <tr>
      <td style='padding:20px 30px 4px'>
        <p style='margin:0 0 10px;color:#334155;font-size:14px;line-height:1.65'>
          O documento para pagamento esta anexado neste e-mail.
        </p>
        <p style='margin:0;color:#64748b;font-size:13px;line-height:1.6'>
          Caso o pagamento ja tenha sido efetuado, por favor desconsidere esta mensagem.
        </p>
        <p style='margin:12px 0 0;color:#64748b;font-size:13px;line-height:1.6'>
          Nao responda esse e-mail.
        </p>
      </td>
    </tr>
    <tr>
      <td style='padding:22px 30px 24px;border-top:1px solid #e2e8f0'>
        <p style='margin:0;color:#0f172a;font-size:14px;font-weight:700'>Equipe Financeira</p>
        <p style='margin:4px 0 0;color:#475569;font-size:13px'>Vale do Sereno</p>
        <p style='margin:8px 0 0;color:#475569;font-size:13px'>Contato: {{support_email}}</p>
        <p style='margin:12px 0 0;color:#94a3b8;font-size:12px'>Mensagem automatica de carater financeiro.</p>
      </td>
    </tr>
  </table>
</div>"""

PRO_REMINDER_SUBJECT = "Lembrete de vencimento | {{customer_name}} | Vale do Sereno"
PRO_REMINDER_BODY = """<div data-email-theme='vs-corp-v5' style='margin:0;padding:28px 12px;background:#ecfdf5;font-family:Arial,sans-serif;color:#0f172a'>
  <table role='presentation' cellspacing='0' cellpadding='0' style='width:100%;max-width:700px;margin:0 auto;background:#ffffff;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden'>
    <tr>
      <td style='height:6px;background:linear-gradient(90deg,#065f46 0%,#10b981 100%)'></td>
    </tr>
    <tr>
      <td style='padding:26px 30px 10px'>
        {{logo_html}}
        <div style='font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:#475569;font-weight:700'>Comunicado Financeiro</div>
        <h1 style='margin:10px 0 6px;font-size:24px;line-height:1.25;color:#0f172a'>Lembrete de vencimento</h1>
        <p style='margin:0;color:#334155;font-size:15px;line-height:1.65'>
          Prezado(a) <b>{{customer_name}}</b>, este e um lembrete sobre o boleto da competencia <b>{{competence}}</b>.
        </p>
        <div style='margin:12px 0 0;display:inline-block;background:#ecfdf5;border:1px solid #a7f3d0;color:#065f46;font-size:12px;font-weight:700;padding:6px 10px;border-radius:999px'>
          Vence em {{days_left}} dia(s)
        </div>
      </td>
    </tr>
    <tr>
      <td style='padding:10px 30px 0'>
        <table role='presentation' cellspacing='0' cellpadding='0' style='width:100%;border:1px solid #e2e8f0;border-radius:12px;background:#f8fafc'>
          <tr>
            <td style='padding:14px 16px;border-bottom:1px solid #e2e8f0;width:40%;font-size:13px;color:#475569;font-weight:700'>Valor</td>
            <td style='padding:14px 16px;border-bottom:1px solid #e2e8f0;font-size:15px;color:#0f172a;font-weight:700'>R$ {{amount}}</td>
          </tr>
          <tr>
            <td style='padding:14px 16px;border-bottom:1px solid #e2e8f0;width:40%;font-size:13px;color:#475569;font-weight:700'>Vencimento</td>
            <td style='padding:14px 16px;border-bottom:1px solid #e2e8f0;font-size:15px;color:#0f172a;font-weight:700'>{{due_date}}</td>
          </tr>
          <tr>
            <td style='padding:14px 16px;width:40%;font-size:13px;color:#475569;font-weight:700'>Prazo</td>
            <td style='padding:14px 16px;font-size:15px;color:#065f46;font-weight:700'>{{days_left}} dia(s)</td>
          </tr>
        </table>
      </td>
    </tr>
    <tr>
      <td style='padding:16px 30px 0'>
        <table role='presentation' cellspacing='0' cellpadding='0' style='width:100%'>
          <tr>
            <td style='padding:0 6px 0 0'>
              <a href='mailto:{{support_email}}?subject=Duvida%20sobre%20vencimento%20{{competence}}' style='display:block;text-align:center;text-decoration:none;background:#065f46;color:#ffffff;font-size:13px;font-weight:700;padding:11px 12px;border-radius:10px'>Preciso de suporte</a>
            </td>
            <td style='padding:0 0 0 6px'>
              <a href='mailto:{{support_email}}?subject=Comprovante%20de%20pagamento%20{{competence}}' style='display:block;text-align:center;text-decoration:none;background:#d1fae5;color:#065f46;font-size:13px;font-weight:700;padding:11px 12px;border-radius:10px'>Enviar comprovante</a>
            </td>
          </tr>
        </table>
      </td>
    </tr>
    <tr>
      <td style='padding:20px 30px 4px'>
        <p style='margin:0;color:#64748b;font-size:13px;line-height:1.6'>
          Se o pagamento ja foi realizado, desconsidere este aviso.
        </p>
      </td>
    </tr>
    <tr>
      <td style='padding:22px 30px 24px;border-top:1px solid #e2e8f0'>
        <p style='margin:0;color:#0f172a;font-size:14px;font-weight:700'>Equipe Financeira</p>
        <p style='margin:4px 0 0;color:#475569;font-size:13px'>Vale do Sereno</p>
        <p style='margin:8px 0 0;color:#475569;font-size:13px'>Contato: {{support_email}}</p>
        <p style='margin:12px 0 0;color:#94a3b8;font-size:12px'>Mensagem automatica de carater financeiro.</p>
      </td>
    </tr>
  </table>
</div>"""


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
        body = t.body_tpl_html or ""
        subj = (t.subject_tpl or "").strip()
        should_upgrade = (
            subj in {OLD_DEFAULT_SUBJECT, LEGACY_PRO_DEFAULT_SUBJECT, PRO_DEFAULT_SUBJECT}
            and PRO_TEMPLATE_MARKER not in body
        ) or "Segue o boleto da competencia" in body
        if should_upgrade:
            t.subject_tpl = PRO_DEFAULT_SUBJECT
            t.body_tpl_html = PRO_DEFAULT_BODY
            t.variables_json = {"vars": ["logo_html", "support_email", "customer_name", "competence", "amount", "due_date"]}
            db.commit()
            db.refresh(t)
        return t
    t = EmailTemplate(
        code=DEFAULT_TEMPLATE_CODE,
        subject_tpl=PRO_DEFAULT_SUBJECT,
        body_tpl_html=PRO_DEFAULT_BODY,
        variables_json={"vars": ["logo_html", "support_email", "customer_name", "competence", "amount", "due_date"]},
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def ensure_default_reminder_template(db: Session):
    t = db.query(EmailTemplate).filter(EmailTemplate.code == DEFAULT_REMINDER_TEMPLATE_CODE).first()
    if t:
        body = t.body_tpl_html or ""
        subj = (t.subject_tpl or "").strip()
        should_upgrade = (
            subj in {OLD_DEFAULT_REMINDER_SUBJECT, LEGACY_PRO_REMINDER_SUBJECT, PRO_REMINDER_SUBJECT}
            and PRO_TEMPLATE_MARKER not in body
        ) or "Este e um lembrete: seu boleto da competencia" in body
        if should_upgrade:
            t.subject_tpl = PRO_REMINDER_SUBJECT
            t.body_tpl_html = PRO_REMINDER_BODY
            t.variables_json = {"vars": ["logo_html", "support_email", "customer_name", "competence", "amount", "due_date", "days_left"]}
            db.commit()
            db.refresh(t)
        return t
    t = EmailTemplate(
        code=DEFAULT_REMINDER_TEMPLATE_CODE,
        subject_tpl=PRO_REMINDER_SUBJECT,
        body_tpl_html=PRO_REMINDER_BODY,
        variables_json={"vars": ["logo_html", "support_email", "customer_name", "competence", "amount", "due_date", "days_left"]},
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


def _format_amount_br(value: float | int) -> str:
    txt = f"{float(value):,.2f}"
    return txt.replace(",", "X").replace(".", ",").replace("X", ".")


def _format_date_br(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def _resolve_email_logo_path() -> Path | None:
    """Escolhe a logo de e-mail disponível no projeto."""
    candidates = [
        Path("arcvstudo.png"),   # nome solicitado pelo usuário
        Path("arcvsctudo.png"),  # nome atualmente existente no projeto
        Path("ARCVSVERDE.png"),
        Path("arc.png"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _logo_html_and_inline() -> tuple[str, list[tuple[Path, str]]]:
    p = _resolve_email_logo_path()
    if not p:
        return "", []
    html = (
        "<div style='margin:0 0 16px 0'>"
        f"<img src='cid:{EMAIL_LOGO_CID}' alt='Vale do Sereno' style='max-width:220px;height:auto;display:block' />"
        "</div>"
    )
    return html, [(p, EMAIL_LOGO_CID)]


def _support_email_for_template() -> str:
    try:
        if SETTINGS_PATH.exists():
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            email_cfg = (data or {}).get("email", {}) or {}
            smtp_from = str(email_cfg.get("smtp_from") or "").strip()
            if smtp_from:
                return smtp_from
    except Exception:
        pass
    return (settings.SMTP_FROM or "financeiro@empresa.com").strip() or "financeiro@empresa.com"


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


def _load_company_external_attachments_for_competence(competence: str) -> dict[str, dict | str]:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    all_competences = data.get(EXTERNAL_COMPANY_ATTACHMENTS_KEY) or {}
    if not isinstance(all_competences, dict):
        return {}
    one_competence = all_competences.get(competence) or {}
    return one_competence if isinstance(one_competence, dict) else {}


def _extract_external_attachment_path(value: dict | str | None) -> Path | None:
    if isinstance(value, str):
        path_str = value.strip()
    elif isinstance(value, dict):
        path_str = str(value.get("file_path") or "").strip()
    else:
        path_str = ""
    if not path_str:
        return None
    return Path(path_str)


def _safe_name(value: str) -> str:
    base = (value or "").strip().replace("/", "-").replace("\\", "-")
    return "_".join(base.split()) or "construtora"


def _company_key(value: str) -> str:
    txt = (value or "").strip().lower()
    txt = unicodedata.normalize("NFKD", txt)
    return "".join(ch for ch in txt if ch.isalnum())


def _extract_rateio_contas_map(db: Session, competence: str) -> dict[str, BoletoAReceber]:
    """Mapeia conta a receber da divisão por nome da construtora (normalizado)."""
    rows = (
        db.query(BoletoAReceber)
        .filter(BoletoAReceber.competence_month == competence)
        .order_by(BoletoAReceber.id.desc())
        .all()
    )
    out: dict[str, BoletoAReceber] = {}
    for row in rows:
        desc = (row.description or "").strip().lower()
        if ("divis" not in desc) or ("cust" not in desc):
            continue
        key = _company_key(row.customer_name or "")
        if key and key not in out:
            out[key] = row
    return out


def _is_unpaid_boleto(b: Boleto) -> bool:
    boleto_status = str((b.status or "")).upper()
    inst_status = str((b.installment.status if b.installment else "") or "").upper()
    return boleto_status not in PAID_LIKE and inst_status not in PAID_LIKE


def send_batch_for_competence(db: Session, competence: str, *, only_overdue: bool = False) -> dict:
    today = date.today()
    tmpl = ensure_default_template(db)
    logo_html, inline_images = _logo_html_and_inline()
    support_email = _support_email_for_template()
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
            "logo_html": logo_html,
            "support_email": support_email,
            "customer_name": cust.name,
            "competence": competence,
            "amount": _format_amount_br(float(b.amount)),
            "due_date": (_format_date_br(b.due_date) if b.due_date else "-"),
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
            send_email([cust.email], subject, body, attachments, inline_images=inline_images)
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


def send_companies_boleto_batch_for_competence(
    db: Session,
    competence: str,
    *,
    company_ids: set[int] | None = None,
) -> dict:
    """Envia e-mails para construtoras com anexo individual (PDF) da cobrança do mês."""
    EmailAttachment.__table__.create(bind=db.get_bind(), checkfirst=True)
    preview = compute_divisao_custos(db=db, competence=competence)
    companies = preview.get("companies") or []
    if company_ids is not None:
        companies = [c for c in companies if int(c.get("id") or 0) in company_ids]
    today = date.today()

    company_emails = _load_company_emails()
    rateio_contas = _extract_rateio_contas_map(db, competence)
    logo_html, inline_images = _logo_html_and_inline()
    support_email = _support_email_for_template()

    batch = EmailBatch(
        competence_month=competence,
        status="ENVIANDO",
        filters_json={
            "kind": "construtoras_boleto",
            "competence": competence,
            "reference_date": today.isoformat(),
        },
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    sent = 0
    failed = 0
    eligible = 0
    skipped_no_email = 0
    skipped_no_conta = 0
    skipped_no_amount = 0
    skipped_no_company = 0

    out_dir = competence_dir(competence) / "emails_construtoras"

    for company in companies:
        company_id = int(company.get("id") or 0)
        company_name = str(company.get("name") or "").strip()
        if company_id <= 0 or not company_name:
            skipped_no_company += 1
            continue

        to_email = (company_emails.get(str(company_id)) or "").strip()
        if not to_email:
            skipped_no_email += 1
            continue

        conta = rateio_contas.get(_company_key(company_name))
        if not conta:
            skipped_no_conta += 1
            continue

        amount = float(conta.amount or 0.0)
        if amount <= 0:
            skipped_no_amount += 1
            continue

        data = compute_company_breakdown(preview, company_id)
        if not data:
            skipped_no_company += 1
            continue

        due_br = _format_date_br(conta.due_date) if conta.due_date else "Nao informado"
        competence_br = competence[5:7] + "/" + competence[:4]

        pdf_bytes = generate_company_cost_division_pdf_bytes(
            association_name="Associação Vale do Sereno",
            competence=competence,
            total_despesas=float(preview.get("total_despesas") or 0.0),
            despesas_breakdown=data.get("breakdown") or [],
            company=data.get("company") or {},
            total_company=float(data.get("total_company") or amount),
            footer_brand="Desenvolvido EasyTech — Facilitando a tecnologia",
        )
        pdf_path = out_dir / f"boleto_construtora_{competence}_{_safe_name(company_name)}.pdf"
        write_bytes(pdf_path, pdf_bytes)

        subject = f"Conta a receber | Divisão de custos {competence_br} | {company_name}"
        body = (
            "<div style='font-family:Arial,sans-serif;color:#0f172a'>"
            f"{logo_html}"
            f"<p>Prezados, <b>{company_name}</b>.</p>"
            f"<p>Segue em anexo a cobrança individual da <b>divisão de custos</b> da competência <b>{competence_br}</b>.</p>"
            "<table style='border-collapse:collapse;width:100%;max-width:520px'>"
            "<tr><td style='padding:8px;border:1px solid #e2e8f0;font-weight:700'>Competência</td>"
            f"<td style='padding:8px;border:1px solid #e2e8f0'>{competence_br}</td></tr>"
            "<tr><td style='padding:8px;border:1px solid #e2e8f0;font-weight:700'>Valor</td>"
            f"<td style='padding:8px;border:1px solid #e2e8f0'>R$ {_format_amount_br(amount)}</td></tr>"
            "<tr><td style='padding:8px;border:1px solid #e2e8f0;font-weight:700'>Vencimento</td>"
            f"<td style='padding:8px;border:1px solid #e2e8f0'>{due_br}</td></tr>"
            "</table>"
            "<p style='margin-top:14px'>Nao responda esse e-mail.</p>"
            "</div>"
        )

        msg = EmailMessage(
            batch_id=batch.id,
            to_emails=to_email,
            subject=subject,
            body_html=body,
            status="PENDENTE",
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)

        eligible += 1
        try:
            send_email([to_email], subject, body, [pdf_path], inline_images=inline_images)
            msg.status = "ENVIADO"
            msg.sent_at = datetime.now(timezone.utc)
            db.add(
                EmailAttachment(
                    email_message_id=msg.id,
                    kind="boleto_construtora",
                    file_path=str(pdf_path),
                )
            )
            sent += 1
        except Exception as exc:
            msg.status = "FALHOU"
            msg.error = str(exc)
            failed += 1
        db.commit()

    batch.status = "CONCLUIDO" if failed == 0 else "FALHOU"
    db.commit()

    return {
        "batch_id": batch.id,
        "sent": sent,
        "failed": failed,
        "eligible": eligible,
        "total_companies": len(companies),
        "skipped_no_email": skipped_no_email,
        "skipped_no_conta": skipped_no_conta,
        "skipped_no_amount": skipped_no_amount,
        "skipped_no_company": skipped_no_company,
        "reference_date": today.isoformat(),
    }


def send_companies_external_attachment_batch_for_competence(
    db: Session,
    competence: str,
    *,
    company_ids: set[int] | None = None,
) -> dict:
    """Envia e-mails para construtoras usando anexo externo previamente cadastrado."""
    EmailAttachment.__table__.create(bind=db.get_bind(), checkfirst=True)
    preview = compute_divisao_custos(db=db, competence=competence)
    companies = preview.get("companies") or []
    if company_ids is not None:
        companies = [c for c in companies if int(c.get("id") or 0) in company_ids]
    today = date.today()

    company_emails = _load_company_emails()
    company_attachments = _load_company_external_attachments_for_competence(competence)
    rateio_contas = _extract_rateio_contas_map(db, competence)
    logo_html, inline_images = _logo_html_and_inline()
    support_email = _support_email_for_template()

    batch = EmailBatch(
        competence_month=competence,
        status="ENVIANDO",
        filters_json={
            "kind": "construtoras_boleto_externo",
            "competence": competence,
            "reference_date": today.isoformat(),
        },
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    sent = 0
    failed = 0
    eligible = 0
    skipped_no_email = 0
    skipped_no_attachment = 0
    skipped_missing_attachment = 0
    skipped_no_company = 0

    competence_br = competence[5:7] + "/" + competence[:4]

    for company in companies:
        company_id = int(company.get("id") or 0)
        company_name = str(company.get("name") or "").strip()
        if company_id <= 0 or not company_name:
            skipped_no_company += 1
            continue

        to_email = (company_emails.get(str(company_id)) or "").strip()
        if not to_email:
            skipped_no_email += 1
            continue

        attachment_value = company_attachments.get(str(company_id))
        attachment_path = _extract_external_attachment_path(attachment_value)
        if not attachment_path:
            skipped_no_attachment += 1
            continue
        if not attachment_path.exists() or not attachment_path.is_file():
            skipped_missing_attachment += 1
            continue

        conta = rateio_contas.get(_company_key(company_name))
        amount = float(conta.amount or 0.0) if conta else 0.0
        due_br = _format_date_br(conta.due_date) if conta and conta.due_date else "Nao informado"

        subject = f"Cobranca financeira | Boleto externo | Competencia {competence_br} | {company_name}"
        body = (
            "<div style='margin:0;padding:26px 12px;background:#f1f5f9;font-family:Arial,sans-serif;color:#0f172a'>"
            "<table role='presentation' cellspacing='0' cellpadding='0' style='width:100%;max-width:700px;margin:0 auto;background:#ffffff;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden'>"
            "<tr><td style='height:6px;background:linear-gradient(90deg,#065f46 0%,#0f766e 100%)'></td></tr>"
            "<tr><td style='padding:24px 28px 8px'>"
            f"{logo_html}"
            "<div style='font-size:11px;letter-spacing:0.1em;text-transform:uppercase;color:#475569;font-weight:700'>Comunicado Financeiro</div>"
            "<h1 style='margin:10px 0 8px;font-size:24px;line-height:1.25;color:#0f172a'>Envio de boleto externo</h1>"
            "<p style='margin:0;color:#334155;font-size:15px;line-height:1.65'>Prezados(as),</p>"
            f"<p style='margin:10px 0 0;color:#334155;font-size:15px;line-height:1.65'>Encaminhamos, para {company_name}, o boleto externo referente a competencia <b>{competence_br}</b>, conforme dados abaixo.</p>"
            "</td></tr>"
            "<tr><td style='padding:10px 28px 0'>"
            "<table role='presentation' cellspacing='0' cellpadding='0' style='width:100%;border:1px solid #e2e8f0;border-radius:12px;background:#f8fafc'>"
            "<tr><td style='padding:14px 16px;border-bottom:1px solid #e2e8f0;width:40%;font-size:13px;color:#475569;font-weight:700'>Competencia</td>"
            f"<td style='padding:14px 16px;border-bottom:1px solid #e2e8f0;font-size:15px;color:#0f172a;font-weight:700'>{competence_br}</td></tr>"
            "<tr><td style='padding:14px 16px;border-bottom:1px solid #e2e8f0;width:40%;font-size:13px;color:#475569;font-weight:700'>Valor</td>"
            f"<td style='padding:14px 16px;border-bottom:1px solid #e2e8f0;font-size:15px;color:#0f172a;font-weight:700'>R$ {_format_amount_br(amount)}</td></tr>"
            "<tr><td style='padding:14px 16px;width:40%;font-size:13px;color:#475569;font-weight:700'>Vencimento</td>"
            f"<td style='padding:14px 16px;font-size:15px;color:#0f172a;font-weight:700'>{due_br}</td></tr>"
            "</table>"
            "</td></tr>"
            "<tr><td style='padding:14px 28px 0'>"
            "<div style='background:#ecfdf5;border:1px solid #a7f3d0;border-radius:10px;padding:10px 12px;color:#065f46;font-size:12px;line-height:1.5'>"
            "Solicitamos, por gentileza, a observancia do vencimento. Caso o pagamento ja tenha sido efetuado, favor desconsiderar este comunicado."
            "</div>"
            "</td></tr>"
            "<tr><td style='padding:20px 28px 24px;border-top:1px solid #e2e8f0'>"
            "<p style='margin:0;color:#334155;font-size:13px;line-height:1.6'>Nao responda esse e-mail.</p>"
            "<p style='margin:10px 0 0;color:#0f172a;font-size:13px;line-height:1.6;font-weight:700'>Atenciosamente,<br/>Equipe Financeira - Vale do Sereno</p>"
            "</td></tr>"
            "</table>"
            "</div>"
        )

        msg = EmailMessage(
            batch_id=batch.id,
            to_emails=to_email,
            subject=subject,
            body_html=body,
            status="PENDENTE",
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)

        eligible += 1
        try:
            send_email([to_email], subject, body, [attachment_path], inline_images=inline_images)
            msg.status = "ENVIADO"
            msg.sent_at = datetime.now(timezone.utc)
            db.add(
                EmailAttachment(
                    email_message_id=msg.id,
                    kind="boleto_construtora_externo",
                    file_path=str(attachment_path),
                )
            )
            sent += 1
        except Exception as exc:
            msg.status = "FALHOU"
            msg.error = str(exc)
            failed += 1
        db.commit()

    batch.status = "CONCLUIDO" if failed == 0 else "FALHOU"
    db.commit()

    return {
        "batch_id": batch.id,
        "sent": sent,
        "failed": failed,
        "eligible": eligible,
        "total_companies": len(companies),
        "skipped_no_email": skipped_no_email,
        "skipped_no_attachment": skipped_no_attachment,
        "skipped_missing_attachment": skipped_missing_attachment,
        "skipped_no_company": skipped_no_company,
        "reference_date": today.isoformat(),
    }


def send_due_soon_reminders(db: Session, *, days_before: tuple[int, ...] = DEFAULT_REMINDER_DAYS) -> dict:
    """Envia lembretes automáticos para boletos prestes a vencer (10,5,3,1 dias)."""
    EmailReminderLog.__table__.create(bind=db.get_bind(), checkfirst=True)
    reminder_tpl = ensure_default_reminder_template(db)
    logo_html, inline_images = _logo_html_and_inline()
    support_email = _support_email_for_template()
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
            "logo_html": logo_html,
            "support_email": support_email,
            "customer_name": cust.name,
            "competence": inst.competence_month,
            "amount": _format_amount_br(float(b.amount)),
            "due_date": _format_date_br(b.due_date),
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
            send_email([email], subject, body, attachments, inline_images=inline_images)
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


def _due_soon_snapshot(db: Session, b: Boleto, *, days_before: tuple[int, ...]) -> dict | None:
    today = date.today()
    inst = b.installment
    if not inst or not inst.receivable or not inst.receivable.customer:
        return None
    if not b.due_date or not _is_unpaid_boleto(b):
        return None

    days_left = (b.due_date - today).days
    max_days = max(days_before) if days_before else 0
    if days_left < 0 or days_left > max_days:
        return None

    cust = inst.receivable.customer
    email = (cust.email or "").strip()

    already = (
        db.query(EmailReminderLog)
        .filter(
            EmailReminderLog.installment_id == inst.id,
            EmailReminderLog.days_before == days_left,
        )
        .first()
    )
    already_sent = bool(already)
    can_send = bool(email) and not already_sent

    status_label = "Pronto para envio"
    status_tone = "emerald"
    if not email:
        status_label = "Cliente sem e-mail"
        status_tone = "amber"
    elif already_sent:
        status_label = "Lembrete ja enviado"
        status_tone = "slate"

    return {
        "target_kind": "boleto",
        "target_id": b.id,
        "boleto_id": b.id,
        "installment_id": inst.id,
        "customer_name": cust.name,
        "customer_email": email,
        "competence": inst.competence_month,
        "due_date": b.due_date,
        "due_date_br": _format_date_br(b.due_date),
        "days_left": days_left,
        "amount": float(b.amount),
        "amount_br": _format_amount_br(float(b.amount)),
        "already_sent": already_sent,
        "can_send": can_send,
        "status_label": status_label,
        "status_tone": status_tone,
    }


def _due_soon_manual_snapshot(br: BoletoAReceber, *, days_before: tuple[int, ...]) -> dict | None:
    today = date.today()
    if not br.due_date:
        return None
    days_left = (br.due_date - today).days
    max_days = max(days_before) if days_before else 0
    if days_left < 0 or days_left > max_days:
        return None

    status_raw = str((br.status or "")).upper()
    if status_raw == "PAGO":
        return None

    email = (br.customer_email or "").strip()
    can_send = bool(email)
    status_label = "Pronto para envio" if can_send else "Cliente sem e-mail"
    status_tone = "emerald" if can_send else "amber"

    return {
        "target_kind": "manual",
        "target_id": int(br.id),
        "boleto_id": None,
        "installment_id": None,
        "customer_name": br.customer_name or "-",
        "customer_email": email,
        "competence": br.competence_month,
        "due_date": br.due_date,
        "due_date_br": _format_date_br(br.due_date),
        "days_left": days_left,
        "amount": float(br.amount or 0),
        "amount_br": _format_amount_br(float(br.amount or 0)),
        "already_sent": False,
        "can_send": can_send,
        "status_label": status_label,
        "status_tone": status_tone,
    }


def list_due_soon_candidates(
    db: Session,
    *,
    days_before: tuple[int, ...] = DEFAULT_REMINDER_DAYS,
    include_manual: bool = True,
) -> list[dict]:
    """Lista boletos nao pagos que vencem em 10/5/3/1 dias com status de envio de lembrete."""
    EmailReminderLog.__table__.create(bind=db.get_bind(), checkfirst=True)
    today = date.today()
    max_days = max(days_before) if days_before else 0
    end_date = today + timedelta(days=max_days)

    boletos = (
        db.query(Boleto)
        .filter(Boleto.due_date >= today, Boleto.due_date <= end_date)
        .order_by(Boleto.due_date.asc(), Boleto.id.asc())
        .all()
    )

    rows = []
    for b in boletos:
        snap = _due_soon_snapshot(db, b, days_before=days_before)
        if snap and (
            bool(snap.get("can_send"))
            or (bool(snap.get("already_sent")) and bool((snap.get("customer_email") or "").strip()))
        ):
            rows.append(snap)

    if include_manual:
        manuais = (
            db.query(BoletoAReceber)
            .filter(BoletoAReceber.due_date >= today, BoletoAReceber.due_date <= end_date)
            .order_by(BoletoAReceber.due_date.asc(), BoletoAReceber.id.asc())
            .all()
        )
        for br in manuais:
            snap = _due_soon_manual_snapshot(br, days_before=days_before)
            if snap and (
                bool(snap.get("can_send"))
                or (bool(snap.get("already_sent")) and bool((snap.get("customer_email") or "").strip()))
            ):
                rows.append(snap)

    rows.sort(key=lambda x: (x.get("due_date"), x.get("target_kind"), int(x.get("target_id") or 0)))
    return rows


def send_due_soon_reminders_for_boleto_ids(
    db: Session,
    *,
    boleto_ids: list[int],
    days_before: tuple[int, ...] = DEFAULT_REMINDER_DAYS,
) -> dict:
    """Envia lembrete manual para boletos especificos (se elegiveis)."""
    EmailReminderLog.__table__.create(bind=db.get_bind(), checkfirst=True)
    reminder_tpl = ensure_default_reminder_template(db)
    logo_html, inline_images = _logo_html_and_inline()
    support_email = _support_email_for_template()
    today = date.today()

    unique_ids = sorted({int(x) for x in boleto_ids if int(x) > 0})
    if not unique_ids:
        return {
            "batch_id": None,
            "requested": 0,
            "sent": 0,
            "failed": 0,
            "eligible": 0,
            "skipped": 0,
            "skip_reasons": ["Nenhum boleto selecionado."],
            "days_before": list(days_before),
            "reference_date": today.isoformat(),
        }

    boletos = (
        db.query(Boleto)
        .filter(Boleto.id.in_(unique_ids))
        .all()
    )
    by_id = {b.id: b for b in boletos}

    batch = EmailBatch(
        competence_month=today.strftime("%Y-%m"),
        status="ENVIANDO",
        filters_json={
            "manual": True,
            "kind": "due_soon_reminder_selected",
            "reference_date": today.isoformat(),
            "days_before": list(days_before),
            "boleto_ids": unique_ids,
        },
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    sent = 0
    failed = 0
    eligible = 0
    skip_reasons: list[str] = []

    for boleto_id in unique_ids:
        b = by_id.get(boleto_id)
        if not b:
            skip_reasons.append(f"Boleto {boleto_id} nao encontrado.")
            continue

        snap = _due_soon_snapshot(db, b, days_before=days_before)
        if not snap:
            skip_reasons.append(f"Boleto {boleto_id} fora da regra (pago, sem cliente ou fora da janela).")
            continue
        if not snap["can_send"]:
            if not snap["customer_email"]:
                skip_reasons.append(f"Boleto {boleto_id}: cliente sem e-mail.")
            elif snap["already_sent"]:
                skip_reasons.append(f"Boleto {boleto_id}: lembrete ja enviado.")
            else:
                skip_reasons.append(f"Boleto {boleto_id}: nao elegivel.")
            continue

        inst = b.installment
        cust = inst.receivable.customer if inst and inst.receivable else None
        if not inst or not cust:
            skip_reasons.append(f"Boleto {boleto_id}: relacionamento de cliente invalido.")
            continue

        eligible += 1
        ctx = {
            "logo_html": logo_html,
            "support_email": support_email,
            "customer_name": cust.name,
            "competence": inst.competence_month,
            "amount": _format_amount_br(float(b.amount)),
            "due_date": _format_date_br(b.due_date),
            "days_left": str(snap["days_left"]),
        }
        subject, body = render_template(reminder_tpl.subject_tpl, reminder_tpl.body_tpl_html, ctx)
        msg = EmailMessage(
            batch_id=batch.id,
            to_emails=snap["customer_email"],
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
            send_email([snap["customer_email"]], subject, body, attachments, inline_images=inline_images)
            msg.status = "ENVIADO"
            msg.sent_at = datetime.now(timezone.utc)
            db.add(
                EmailReminderLog(
                    installment_id=inst.id,
                    boleto_id=b.id,
                    customer_email=snap["customer_email"],
                    due_date=b.due_date,
                    days_before=snap["days_left"],
                )
            )
            sent += 1
        except Exception as exc:
            msg.status = "FALHOU"
            msg.error = str(exc)
            failed += 1

        db.commit()

    batch.status = "CONCLUIDO" if failed == 0 else "FALHOU"
    db.commit()

    return {
        "batch_id": batch.id,
        "requested": len(unique_ids),
        "sent": sent,
        "failed": failed,
        "eligible": eligible,
        "skipped": len(unique_ids) - eligible,
        "skip_reasons": skip_reasons[:20],
        "days_before": list(days_before),
        "reference_date": today.isoformat(),
    }


def send_due_soon_manual_reminders_for_ids(
    db: Session,
    *,
    manual_ids: list[int],
    days_before: tuple[int, ...] = DEFAULT_REMINDER_DAYS,
) -> dict:
    """Envia lembretes para boletos_a_receber selecionados (cadastro manual)."""
    reminder_tpl = ensure_default_reminder_template(db)
    logo_html, inline_images = _logo_html_and_inline()
    support_email = _support_email_for_template()
    today = date.today()

    unique_ids = sorted({int(x) for x in manual_ids if int(x) > 0})
    if not unique_ids:
        return {
            "batch_id": None,
            "requested": 0,
            "sent": 0,
            "failed": 0,
            "eligible": 0,
            "skipped": 0,
            "skip_reasons": ["Nenhum boleto manual selecionado."],
            "days_before": list(days_before),
            "reference_date": today.isoformat(),
        }

    manuais = db.query(BoletoAReceber).filter(BoletoAReceber.id.in_(unique_ids)).all()
    by_id = {int(x.id): x for x in manuais}

    batch = EmailBatch(
        competence_month=today.strftime("%Y-%m"),
        status="ENVIANDO",
        filters_json={
            "manual": True,
            "kind": "due_soon_reminder_selected_manual",
            "reference_date": today.isoformat(),
            "days_before": list(days_before),
            "manual_ids": unique_ids,
        },
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    sent = 0
    failed = 0
    eligible = 0
    skip_reasons: list[str] = []

    for manual_id in unique_ids:
        br = by_id.get(manual_id)
        if not br:
            skip_reasons.append(f"Boleto manual {manual_id} nao encontrado.")
            continue

        snap = _due_soon_manual_snapshot(br, days_before=days_before)
        if not snap:
            skip_reasons.append(f"Boleto manual {manual_id} fora da janela de vencimento.")
            continue
        if not snap["can_send"]:
            skip_reasons.append(f"Boleto manual {manual_id}: cliente sem e-mail.")
            continue

        eligible += 1
        ctx = {
            "logo_html": logo_html,
            "support_email": support_email,
            "customer_name": snap["customer_name"],
            "competence": snap["competence"],
            "amount": _format_amount_br(float(br.amount or 0)),
            "due_date": _format_date_br(br.due_date),
            "days_left": str(snap["days_left"]),
        }
        subject, body = render_template(reminder_tpl.subject_tpl, reminder_tpl.body_tpl_html, ctx)
        msg = EmailMessage(
            batch_id=batch.id,
            to_emails=snap["customer_email"],
            subject=subject,
            body_html=body,
            status="PENDENTE",
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)

        try:
            send_email([snap["customer_email"]], subject, body, [], inline_images=inline_images)
            msg.status = "ENVIADO"
            msg.sent_at = datetime.now(timezone.utc)
            sent += 1
        except Exception as exc:
            msg.status = "FALHOU"
            msg.error = str(exc)
            failed += 1

        db.commit()

    batch.status = "CONCLUIDO" if failed == 0 else "FALHOU"
    db.commit()

    return {
        "batch_id": batch.id,
        "requested": len(unique_ids),
        "sent": sent,
        "failed": failed,
        "eligible": eligible,
        "skipped": len(unique_ids) - eligible,
        "skip_reasons": skip_reasons[:20],
        "days_before": list(days_before),
        "reference_date": today.isoformat(),
    }
