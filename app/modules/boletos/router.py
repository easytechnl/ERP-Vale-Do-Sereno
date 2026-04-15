import datetime
import json
from pathlib import Path

from fastapi import APIRouter, Request, Depends, UploadFile, File, Form
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.templating import templates
from app.core.ui_feedback import toast_redirect
from app.core.utils import clamp_competence, current_competence
from app.models.boletos import Boleto
from app.models.boletos_pagar import BoletoAPagar
from app.models.boletos_receber import BoletoAReceber
from app.models.customer import Customer
from app.models.lancamentos import LedgerEntry
from app.models.rateio import RateioCompany
from app.models.receber import Installment, Receivable
from app.modules.auth.utils import require_login
from app.modules.boletos.service import (
    ensure_boletos_pagar_schema,
    generate_boletos_for_competence,
    generate_cnab_remittance,
    import_cnab_return,
)
from app.modules.lancamentos.service import create_entry


router = APIRouter(prefix="/boletos", tags=["boletos"])
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


def _cadastro_url(competence: str) -> str:
    return f"/boletos/cadastro?competence={competence}"


def _receber_cadastro_url(competence: str) -> str:
    return f"/boletos/receber-cadastro?competence={competence}"


def _toast_back_or(
    default_url: str,
    return_to: str | None = None,
    *,
    kind: str = "ok",
    message: str | None = None,
) -> RedirectResponse:
    target = (return_to or "").strip()
    url = target if target.startswith("/") else default_url
    return toast_redirect(url, kind=kind, message=message)


def _norm_status_pagar(status: str) -> str:
    st = (status or "").strip().upper()
    mapping = {
        "PAGO": "PAGO",
        "PAGA": "PAGO",
        "A VENCER": "A_VENCER",
        "AVENCER": "A_VENCER",
        "A_VENCER": "A_VENCER",
        "VENCIDO": "VENCIDO",
        "VENCIDA": "VENCIDO",
    }
    return mapping.get(st, "A_VENCER")


def _recent_payable_beneficiarios(db: Session, limit: int = 8) -> list[str]:
    rows = (
        db.query(BoletoAPagar.beneficiario)
        .filter(BoletoAPagar.beneficiario.isnot(None))
        .filter(func.trim(BoletoAPagar.beneficiario) != "")
        .order_by(BoletoAPagar.id.desc())
        .limit(max(limit * 5, 20))
        .all()
    )

    recent: list[str] = []
    seen: set[str] = set()
    for row in rows:
        name = str(row[0] or "").strip()
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        recent.append(name)
        if len(recent) >= limit:
            break
    return recent


def _payable_entry_description(b: BoletoAPagar) -> str:
    desc = f"Boleto pago: {b.beneficiario}"
    if b.descricao:
        desc = f"{desc} - {b.descricao}"
    if getattr(b, "numero_nota_fiscal", None):
        desc = f"{desc} - NF {b.numero_nota_fiscal}"
    return desc


@router.get("")
def boletos_page(
    request: Request,
    competence: str | None = None,
    view: str = "all",
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = clamp_competence(competence, fallback=current_competence()) or current_competence()
    return RedirectResponse(url=_cadastro_url(competence), status_code=302)


@router.post("/{boleto_id}/status")
def update_boleto_status(
    boleto_id: int,
    competence: str = Form(...),
    status: str = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = clamp_competence(competence) or competence
    b = db.query(Boleto).filter(Boleto.id == boleto_id).first()
    if not b:
        return toast_redirect(
            _cadastro_url(competence),
            kind="err",
            message="Boleto nao encontrado.",
        )

    new_status = (status or "").upper().strip()
    b.status = status

    inst = db.query(Installment).filter(Installment.id == b.installment_id).first()
    if inst:
        is_paid = ("PAG" in new_status) or ("BAIX" in new_status)
        if is_paid:
            inst.status = "BAIXADA"
            if not inst.paid_at:
                inst.paid_at = datetime.date.today()
        elif "CANC" in new_status:
            inst.status = "CANCELADA"
            inst.paid_at = None
        else:
            inst.status = "ABERTA"
            inst.paid_at = None

        tag = f"AUTO:BOLETO_RECEBIDO:{b.id}"
        existing = db.query(LedgerEntry).filter(LedgerEntry.notes == tag).first()

        rec = db.query(Receivable).filter(Receivable.id == inst.receivable_id).first()
        cust = db.query(Customer).filter(Customer.id == rec.customer_id).first() if rec else None

        desc_parts = ["Recebimento boleto"]
        if cust:
            desc_parts.append(cust.name)
        if b.nosso_numero:
            desc_parts.append(f"NN {b.nosso_numero}")
        description = " - ".join(desc_parts)

        if is_paid:
            if not existing:
                create_entry(
                    db,
                    competence=inst.competence_month,
                    entry_date=inst.paid_at or datetime.date.today(),
                    kind="ENTRADA",
                    amount=float(b.amount or inst.amount or 0.0),
                    description=description,
                    status="REALIZADO",
                    customer_id=(cust.id if cust else None),
                    notes=tag,
                )
            else:
                existing.kind = "ENTRADA"
                existing.status = "REALIZADO"
                existing.amount = float(b.amount or inst.amount or 0.0)
                existing.entry_date = inst.paid_at or existing.entry_date
                existing.description = description
                existing.customer_id = cust.id if cust else existing.customer_id
                existing.competence_month = inst.competence_month
        elif existing:
            db.delete(existing)

    db.commit()
    return toast_redirect(_cadastro_url(competence))


@router.get("/pdf/{boleto_id}")
def download_boleto_pdf(boleto_id: int, user=Depends(require_login), db: Session = Depends(get_db)):
    b = db.query(Boleto).filter(Boleto.id == boleto_id).first()
    if not b or not b.pdf_path:
        return {"error": "PDF nao encontrado"}
    return FileResponse(path=b.pdf_path, filename=f"boleto_{b.id}.pdf", media_type="application/pdf")


@router.post("/api/{competence}/gerar")
def api_gerar_boletos(competence: str, user=Depends(require_login), db: Session = Depends(get_db)):
    competence = clamp_competence(competence) or competence
    return generate_boletos_for_competence(db, competence)


@router.post("/api/{competence}/cnab/remessa")
def api_gerar_remessa(competence: str, user=Depends(require_login), db: Session = Depends(get_db)):
    competence = clamp_competence(competence) or competence
    return generate_cnab_remittance(db, competence)


@router.post("/api/{competence}/cnab/retorno")
async def api_importar_retorno(
    competence: str,
    file: UploadFile = File(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = clamp_competence(competence) or competence
    data = await file.read()
    return import_cnab_return(db, competence, file.filename, data)


@router.get("/cadastro")
def boletos_cadastro_page(
    request: Request,
    competence: str | None = None,
    view: str = "all",
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    today = datetime.date.today()
    competence = clamp_competence(competence, fallback=current_competence()) or current_competence()
    ensure_boletos_pagar_schema(db)

    rows = (
        db.query(BoletoAPagar)
        .filter(BoletoAPagar.competence_month == competence)
        .order_by(BoletoAPagar.id.desc())
        .all()
    )

    boletos = []
    for b in rows:
        due = b.due_date
        st = (b.status or "A_VENCER").upper()
        is_paid = st == "PAGO"
        overdue = bool(due and (not is_paid) and (due < today))
        due_soon = bool(due and (not is_paid) and (0 <= (due - today).days <= 5))
        boletos.append(
            {
                "id": b.id,
                "beneficiario": b.beneficiario,
                "descricao": b.descricao or "",
                "numero_nota_fiscal": getattr(b, "numero_nota_fiscal", None) or "",
                "due_date": b.due_date,
                "amount": float(b.amount or 0.0),
                "status": st,
                "paid_at": b.paid_at,
                "barcode": b.barcode or "",
                "digitable_line": b.digitable_line or "",
                "overdue": overdue,
                "due_soon": due_soon,
                "notes": b.notes or "",
            }
        )

    paid = [x for x in boletos if x["status"] == "PAGO"]
    pending = [x for x in boletos if x["status"] != "PAGO"]
    overdue = [x for x in pending if x["overdue"]]
    due_soon = [x for x in pending if x["due_soon"]]

    def _sum(items):
        return float(sum(x["amount"] for x in items))

    stats = {
        "paid_total": _sum(paid),
        "pending_total": _sum(pending),
        "overdue_total": _sum(overdue),
        "due_soon_total": _sum(due_soon),
        "paid_count": len(paid),
        "pending_count": len(pending),
        "overdue_count": len(overdue),
        "due_soon_count": len(due_soon),
        "all_count": len(boletos),
    }

    view = (view or "all").lower()
    if view == "paid":
        visible = paid
    elif view == "pending":
        visible = pending
    elif view == "overdue":
        visible = overdue
    elif view == "due_soon":
        visible = due_soon
    else:
        visible = boletos

    return templates.TemplateResponse(
        "boletos/cadastro.html",
        {
            "request": request,
            "user": user,
            "competence": competence,
            "boletos": visible,
            "stats": stats,
            "view": view,
            "recent_beneficiarios": _recent_payable_beneficiarios(db),
        },
    )


@router.post("/cadastro/create")
def boletos_cadastro_create(
    competence: str = Form(...),
    beneficiario: str = Form(...),
    descricao: str = Form(""),
    numero_nota_fiscal: str = Form(""),
    due_date: str = Form(""),
    amount: float = Form(...),
    status: str = Form("A_VENCER"),
    barcode: str = Form(""),
    digitable_line: str = Form(""),
    notes: str = Form(""),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = clamp_competence(competence) or competence
    ensure_boletos_pagar_schema(db)
    due = datetime.date.fromisoformat(due_date) if due_date.strip() else None
    st = _norm_status_pagar(status)

    b = BoletoAPagar(
        competence_month=competence,
        beneficiario=beneficiario.strip(),
        descricao=descricao.strip() or None,
        numero_nota_fiscal=numero_nota_fiscal.strip() or None,
        due_date=due,
        amount=float(amount),
        status=st,
        paid_at=(datetime.date.today() if st == "PAGO" else None),
        barcode=barcode.strip() or None,
        digitable_line=digitable_line.strip() or None,
        notes=notes.strip() or None,
    )
    db.add(b)
    db.commit()
    db.refresh(b)

    if st == "PAGO":
        tag = f"AUTO:BOLETO_APAGAR:{b.id}"
        existing = db.query(LedgerEntry).filter(LedgerEntry.notes == tag).first()
        if not existing:
            create_entry(
                db,
                competence=b.competence_month,
                entry_date=b.paid_at or datetime.date.today(),
                kind="SAIDA",
                amount=float(b.amount or 0.0),
                description=_payable_entry_description(b),
                status="REALIZADO",
                category="BOLETOS",
                notes=tag,
            )

    return toast_redirect(_cadastro_url(competence))


@router.post("/cadastro/{boleto_id}/status")
def boletos_cadastro_update_status(
    boleto_id: int,
    competence: str = Form(...),
    status: str = Form(...),
    return_to: str = Form(""),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = clamp_competence(competence) or competence
    ensure_boletos_pagar_schema(db)
    b = db.query(BoletoAPagar).get(boleto_id)
    if not b:
        return _toast_back_or(
            _cadastro_url(competence),
            return_to,
            kind="err",
            message="Conta a pagar nao encontrada.",
        )

    st = _norm_status_pagar(status)
    b.status = st
    if st == "PAGO" and b.paid_at is None:
        b.paid_at = datetime.date.today()
    if st != "PAGO":
        b.paid_at = None

    tag = f"AUTO:BOLETO_APAGAR:{b.id}"
    existing = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.notes == tag)
        .order_by(LedgerEntry.id.desc())
        .all()
    )

    if st == "PAGO":
        if not existing:
            create_entry(
                db,
                competence=b.competence_month,
                entry_date=b.paid_at or datetime.date.today(),
                kind="SAIDA",
                amount=float(b.amount or 0.0),
                description=_payable_entry_description(b),
                status="REALIZADO",
                category="BOLETOS",
                notes=tag,
            )
    else:
        for ent in existing:
            db.delete(ent)

    db.commit()
    return _toast_back_or(_cadastro_url(competence), return_to)


@router.post("/cadastro/{boleto_id}/delete")
def boletos_cadastro_delete(
    boleto_id: int,
    competence: str = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = clamp_competence(competence) or competence
    ensure_boletos_pagar_schema(db)
    b = db.query(BoletoAPagar).get(boleto_id)
    if b:
        db.delete(b)
        db.commit()
    return toast_redirect(_cadastro_url(competence))


@router.get("/receber-cadastro")
def boletos_receber_cadastro_page(
    request: Request,
    competence: str | None = None,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = clamp_competence(competence, fallback=current_competence()) or current_competence()

    company_emails = _load_company_emails()
    companies = (
        db.query(RateioCompany)
        .filter(RateioCompany.active == True)
        .order_by(RateioCompany.name.asc())
        .all()
    )
    companies_ui = [{"id": c.id, "name": c.name, "email": company_emails.get(str(c.id)) or ""} for c in companies]

    rows = (
        db.query(BoletoAReceber)
        .filter(BoletoAReceber.competence_month == competence)
        .order_by(BoletoAReceber.id.desc())
        .all()
    )

    today = datetime.date.today()
    items = []
    for b in rows:
        st = (b.status or "A_VENCER").upper().strip()
        is_paid = st == "PAGO"
        due = b.due_date
        overdue = bool(due and (not is_paid) and (due < today))
        due_soon = bool(due and (not is_paid) and (0 <= (due - today).days <= 5))
        items.append(
            {
                "id": b.id,
                "customer_name": b.customer_name,
                "customer_email": b.customer_email,
                "description": b.description or "",
                "due_date": b.due_date,
                "amount": float(b.amount or 0.0),
                "status": st,
                "paid_at": b.paid_at,
                "overdue": overdue,
                "due_soon": due_soon,
            }
        )

    linked_rows = (
        db.query(Boleto, Installment, Receivable, Customer)
        .join(Installment, Installment.id == Boleto.installment_id)
        .join(Receivable, Receivable.id == Installment.receivable_id)
        .join(Customer, Customer.id == Receivable.customer_id)
        .filter(Installment.competence_month == competence)
        .order_by(Boleto.id.desc())
        .all()
    )
    linked_boletos = []
    for b, inst, rec, cust in linked_rows:
        status_raw = (b.status or inst.status or "").upper().strip()
        if ("PAG" in status_raw) or ("BAIX" in status_raw):
            status_norm = "PAGO"
        elif "VENC" in status_raw:
            status_norm = "VENCIDO"
        else:
            status_norm = "A_VENCER"
        linked_boletos.append(
            {
                "id": b.id,
                "customer_name": cust.name,
                "customer_email": cust.email or "",
                "due_date": b.due_date or inst.due_date,
                "amount": float(b.amount or inst.amount or rec.amount or 0.0),
                "description": rec.description or "",
                "nosso_numero": b.nosso_numero or "",
                "digitable_line": b.digitable_line or "",
                "status": status_norm,
            }
        )

    return templates.TemplateResponse(
        "boletos/receber_cadastro.html",
        {
            "request": request,
            "user": user,
            "competence": competence,
            "items": items,
            "companies": companies_ui,
            "linked_boletos": linked_boletos,
        },
    )


@router.post("/receber-cadastro/create")
def boletos_receber_cadastro_create(
    competence: str = Form(...),
    construtora_id: str = Form(""),
    source_boleto_id: str = Form(""),
    customer_name: str = Form(...),
    customer_email: str = Form(""),
    description: str = Form(""),
    due_date: str = Form(""),
    amount: float = Form(...),
    status: str = Form("A_VENCER"),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = clamp_competence(competence) or competence
    selected_company = None
    company_email = ""
    if (construtora_id or "").strip().isdigit():
        selected_company = db.query(RateioCompany).filter(RateioCompany.id == int(construtora_id)).first()
        company_email = _load_company_emails().get(str(int(construtora_id)), "")

    resolved_name = (customer_name or "").strip() or ((selected_company.name if selected_company else "") or "")
    resolved_email = (customer_email or "").strip() or company_email
    resolved_desc = (description or "").strip() or None
    resolved_due = datetime.date.fromisoformat(due_date) if (due_date or "").strip() else None
    resolved_amount = float(amount or 0.0)
    resolved_status = (status or "A_VENCER").upper().strip()

    linked = None
    if (source_boleto_id or "").strip().isdigit():
        linked = (
            db.query(Boleto, Installment, Receivable, Customer)
            .join(Installment, Installment.id == Boleto.installment_id)
            .join(Receivable, Receivable.id == Installment.receivable_id)
            .join(Customer, Customer.id == Receivable.customer_id)
            .filter(Boleto.id == int(source_boleto_id))
            .filter(Installment.competence_month == competence)
            .first()
        )

    if linked:
        b_src, inst, rec, cust = linked
        resolved_name = cust.name or resolved_name
        resolved_email = cust.email or resolved_email
        resolved_due = b_src.due_date or inst.due_date or resolved_due
        resolved_amount = float(b_src.amount or inst.amount or rec.amount or resolved_amount or 0.0)
        if not resolved_desc:
            fallback_desc = (rec.description or "").strip()
            if not fallback_desc:
                fallback_desc = f"Boleto #{b_src.id}"
                if b_src.nosso_numero:
                    fallback_desc = f"{fallback_desc} - NN {b_src.nosso_numero}"
            resolved_desc = fallback_desc or None
        if resolved_status == "A_VENCER":
            status_raw = (b_src.status or inst.status or "").upper().strip()
            if ("PAG" in status_raw) or ("BAIX" in status_raw):
                resolved_status = "PAGO"
            elif "VENC" in status_raw:
                resolved_status = "VENCIDO"
            else:
                resolved_status = "A_VENCER"

    b = BoletoAReceber(
        competence_month=competence,
        customer_name=resolved_name,
        customer_email=resolved_email or None,
        description=resolved_desc,
        due_date=resolved_due,
        amount=float(resolved_amount or 0.0),
        status=resolved_status,
    )
    if b.status == "PAGO":
        b.paid_at = datetime.datetime.utcnow()
    db.add(b)
    db.commit()
    db.refresh(b)

    if (b.status or "").upper().strip() == "PAGO":
        tag = f"AUTO:BOLETO_RECEBER_CAD:{b.id}"
        existing = db.query(LedgerEntry).filter(LedgerEntry.notes == tag).first()
        if not existing:
            entry_date = b.paid_at.date() if b.paid_at else datetime.date.today()
            desc = f"Recebimento boleto (cadastro) - {b.customer_name}"
            create_entry(
                db,
                competence=competence,
                entry_date=entry_date,
                kind="ENTRADA",
                amount=float(b.amount or 0.0),
                description=desc,
                status="REALIZADO",
                notes=tag,
            )

    return toast_redirect(_receber_cadastro_url(competence))


@router.post("/receber-cadastro/{boleto_id}/status")
def boletos_receber_cadastro_update_status(
    boleto_id: int,
    competence: str = Form(...),
    status: str = Form(...),
    return_to: str = Form(""),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = clamp_competence(competence) or competence
    b = db.query(BoletoAReceber).filter(BoletoAReceber.id == boleto_id).first()
    if not b:
        return _toast_back_or(
            _receber_cadastro_url(competence),
            return_to,
            kind="err",
            message="Conta a receber nao encontrada.",
        )

    new_status = (status or "A_VENCER").upper().strip()
    b.status = new_status

    tag = f"AUTO:BOLETO_RECEBER_CAD:{b.id}"
    existing = db.query(LedgerEntry).filter(LedgerEntry.notes == tag).first()

    if new_status == "PAGO":
        if not b.paid_at:
            b.paid_at = datetime.datetime.utcnow()
        if not existing:
            desc = f"Recebimento boleto (cadastro) - {b.customer_name}"
            create_entry(
                db,
                competence=b.competence_month,
                entry_date=b.paid_at.date() if b.paid_at else datetime.date.today(),
                kind="ENTRADA",
                amount=float(b.amount or 0.0),
                description=desc,
                status="REALIZADO",
                notes=tag,
            )
        else:
            existing.kind = "ENTRADA"
            existing.status = "REALIZADO"
            existing.amount = float(b.amount or 0.0)
            existing.competence_month = b.competence_month
            existing.description = f"Recebimento boleto (cadastro) - {b.customer_name}"
    else:
        b.paid_at = None
        if existing:
            db.delete(existing)

    db.commit()
    return _toast_back_or(_receber_cadastro_url(competence), return_to)


@router.post("/receber-cadastro/{boleto_id}/delete")
def boletos_receber_cadastro_delete(
    boleto_id: int,
    competence: str = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = clamp_competence(competence) or competence
    b = db.query(BoletoAReceber).filter(BoletoAReceber.id == boleto_id).first()
    if b:
        tag = f"AUTO:BOLETO_RECEBER_CAD:{b.id}"
        existing = db.query(LedgerEntry).filter(LedgerEntry.notes == tag).first()
        if existing:
            db.delete(existing)
        db.delete(b)
        db.commit()

    return toast_redirect(_receber_cadastro_url(competence))


@router.post("/receber-cadastro/{boleto_id}/email")
def boletos_receber_cadastro_update_email(
    boleto_id: int,
    competence: str = Form(...),
    customer_email: str = Form(""),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = clamp_competence(competence) or competence
    b = db.query(BoletoAReceber).filter(BoletoAReceber.id == boleto_id).first()
    if b:
        b.customer_email = customer_email.strip() or None
        db.commit()
    return toast_redirect(_receber_cadastro_url(competence))
