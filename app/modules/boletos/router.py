import json
from pathlib import Path

from fastapi import APIRouter, Request, Depends, UploadFile, File, Form
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session
import datetime

from app.core.templating import templates
from app.core.deps import get_db
from app.modules.auth.utils import require_login
from app.models.boletos import Boleto, CnabRemittance, CnabReturnImport
from app.models.receber import Installment, Receivable
from app.models.customer import Customer
from app.models.boletos_pagar import BoletoAPagar
from app.models.boletos_receber import BoletoAReceber
from app.models.notas_fiscais import NotaFiscal
from app.models.rateio import RateioCompany
from app.models.lancamentos import LedgerEntry
from app.modules.lancamentos.service import create_entry
from app.modules.boletos.service import (
    generate_boletos_for_competence,
    generate_cnab_remittance,
    import_cnab_return,
    ensure_boletos_receber_schema,
)

router = APIRouter(prefix="/boletos", tags=["boletos"])
SETTINGS_PATH = Path("data/configuracoes.json")


def _normalize_payable_status(status: str) -> str:
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


@router.get("")
def boletos_page(request: Request, competence: str | None = None, view: str = "all", user=Depends(require_login), db: Session = Depends(get_db)):
    today = datetime.date.today()

    if not competence:
        competence = today.strftime("%Y-%m")

    rows = (
        db.query(Boleto, Installment, Receivable, Customer)
        .join(Installment, Installment.id == Boleto.installment_id)
        .join(Receivable, Receivable.id == Installment.receivable_id)
        .join(Customer, Customer.id == Receivable.customer_id)
        .filter(Installment.competence_month == competence)
        .order_by(Boleto.id.desc())
        .all()
    )

    boletos = []
    for (b, inst, rec, cust) in rows:
        due = b.due_date
        amount = float(b.amount or 0.0)
        status = (b.status or "PENDENTE").upper()
        is_paid = status.startswith("PAGO")
        overdue = (due is not None and (not is_paid) and (due < today))
        due_soon = (due is not None and (not is_paid) and (0 <= (due - today).days <= 5))

        reminder = (
            f"Assunto: Boleto próximo do vencimento (competência {competence})\n\n"
            f"Olá, {cust.name}.\n\n"
            f"Este é um lembrete de que seu boleto está próximo do vencimento.\n"
            f"- Vencimento: {due.strftime('%d/%m/%Y') if due else '—'}\n"
            f"- Valor: R$ {amount:,.2f}\n"
            f"- Linha digitável: {b.digitable_line or '—'}\n\n"
            f"Se já realizou o pagamento, desconsidere esta mensagem.\n\n"
            f"Atenciosamente,\nAssociação Vale do Sereno\n"
            f"(Sistema: Painel Financeiro ARCVS)"
        )

        boletos.append({
            "id": b.id,
            "nosso_numero": b.nosso_numero,
            "due_date": due,
            "amount": amount,
            "status": status,
            "pdf_path": b.pdf_path,
            "digitable_line": b.digitable_line,
            "customer_name": cust.name,
            "customer_email": cust.email,
            "is_paid": is_paid,
            "overdue": overdue,
            "due_soon": due_soon,
            "reminder_text": reminder,
        })

    # Totais
    paid = [x for x in boletos if x["is_paid"]]
    pending = [x for x in boletos if not x["is_paid"]]
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

    # Filtro de visualização
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

    remessas = db.query(CnabRemittance).filter(CnabRemittance.competence_month == competence).order_by(CnabRemittance.id.desc()).all()
    retornos = db.query(CnabReturnImport).filter(CnabReturnImport.competence_month == competence).order_by(CnabReturnImport.id.desc()).all()

    return templates.TemplateResponse("boletos/boletos.html", {
        "request": request, "user": user, "competence": competence,
        "boletos": visible, "stats": stats, "view": view,
        "remessas": remessas, "retornos": retornos
    })



@router.post("/{boleto_id}/status")
def update_boleto_status(
    boleto_id: int,
    competence: str = Form(...),
    status: str = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    b = db.query(Boleto).filter(Boleto.id == boleto_id).first()
    if not b:
        return {"error": "Boleto não encontrado"}
    old_status = (b.status or "").upper().strip()
    new_status = (status or "").upper().strip()
    b.status = status

    # mantém parcela sincronizada com o status do boleto
    inst = db.query(Installment).filter(Installment.id == b.installment_id).first()
    if inst:
        st = new_status
        is_paid = ("PAG" in st) or ("BAIX" in st)
        if is_paid:
            inst.status = "BAIXADA"
            # marca data de pagamento se ainda não tiver
            if not inst.paid_at:
                inst.paid_at = datetime.date.today()
        elif "CANC" in st:
            inst.status = "CANCELADA"
            inst.paid_at = None
        else:
            inst.status = "ABERTA"
            inst.paid_at = None

        # ==========================================================
        # FINANCEIRO: boleto pago pelo cliente => ENTRADA no saldo
        # - cria LedgerEntry automático quando vira pago
        # - remove LedgerEntry automático quando deixa de ser pago
        # ==========================================================
        tag = f"AUTO:BOLETO_RECEBIDO:{b.id}"
        existing = db.query(LedgerEntry).filter(LedgerEntry.notes == tag).first()

        # Busca cliente/descrição (para deixar o lançamento legível)
        rec = db.query(Receivable).filter(Receivable.id == inst.receivable_id).first()
        cust = None
        if rec:
            cust = db.query(Customer).filter(Customer.id == rec.customer_id).first()

        desc_parts = ["Recebimento boleto"]
        if cust:
            desc_parts.append(cust.name)
        if b.nosso_numero:
            desc_parts.append(f"NN {b.nosso_numero}")
        description = " - ".join(desc_parts)

        if is_paid:
            # cria entrada se não existir
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
                # se já existe, só garante valor/data corretos (sem duplicar)
                existing.kind = "ENTRADA"
                existing.status = "REALIZADO"
                existing.amount = float(b.amount or inst.amount or 0.0)
                existing.entry_date = inst.paid_at or existing.entry_date
                existing.description = description
                existing.customer_id = (cust.id if cust else existing.customer_id)
                existing.competence_month = inst.competence_month
        else:
            # deixou de ser pago => remove lançamento automático
            if existing:
                db.delete(existing)
    db.commit()
    return RedirectResponse(f"/boletos?competence={competence}", status_code=303)

@router.get("/pdf/{boleto_id}")
def download_boleto_pdf(boleto_id: int, user=Depends(require_login), db: Session = Depends(get_db)):
    b = db.query(Boleto).filter(Boleto.id == boleto_id).first()
    if not b or not b.pdf_path:
        return {"error": "PDF não encontrado"}
    return FileResponse(path=b.pdf_path, filename=f"boleto_{b.id}.pdf", media_type="application/pdf")

@router.post("/api/{competence}/gerar")
def api_gerar_boletos(competence: str, user=Depends(require_login), db: Session = Depends(get_db)):
    return generate_boletos_for_competence(db, competence)

@router.post("/api/{competence}/cnab/remessa")
def api_gerar_remessa(competence: str, user=Depends(require_login), db: Session = Depends(get_db)):
    return generate_cnab_remittance(db, competence)

@router.post("/api/{competence}/cnab/retorno")
async def api_importar_retorno(competence: str, file: UploadFile = File(...), user=Depends(require_login), db: Session = Depends(get_db)):
    data = await file.read()
    return import_cnab_return(db, competence, file.filename, data)


# =====================================================================
# Boletos cadastrados (contas a pagar) + vínculo com Nota Fiscal
# =====================================================================


def _redirect_cadastro(competence: str) -> RedirectResponse:
    return RedirectResponse(url=f"/boletos/cadastro?competence={competence}", status_code=303)


def _redirect_back_or(default_url: str, return_to: str | None = None) -> RedirectResponse:
    target = (return_to or "").strip()
    if target.startswith("/"):
        return RedirectResponse(url=target, status_code=303)
    return RedirectResponse(url=default_url, status_code=303)


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


@router.get("/cadastro")
def boletos_cadastro_page(
    request: Request,
    competence: str | None = None,
    view: str = "all",
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    today = datetime.date.today()
    competence = competence or today.strftime("%Y-%m")

    rows = (
        db.query(BoletoAPagar)
        .filter(BoletoAPagar.competence_month == competence)
        .order_by(BoletoAPagar.id.desc())
        .all()
    )

    # notas da competência para o select
    notas = (
        db.query(NotaFiscal)
        .filter(NotaFiscal.competence_month == competence)
        .order_by(NotaFiscal.id.desc())
        .all()
    )
    notas_ui = [{"id": n.id, "numero": n.numero, "fornecedor": n.fornecedor or "", "amount": float(n.amount or 0.0)} for n in notas]

    boletos = []
    for b in rows:
        due = b.due_date
        st = (b.status or "A_VENCER").upper()
        is_paid = st == "PAGO"
        overdue = bool(due and (not is_paid) and (due < today))
        due_soon = bool(due and (not is_paid) and (0 <= (due - today).days <= 5))
        nf = b.nota_fiscal
        boletos.append(
            {
                "id": b.id,
                "beneficiario": b.beneficiario,
                "descricao": b.descricao or "",
                "due_date": b.due_date,
                "amount": float(b.amount or 0.0),
                "status": st,
                "paid_at": b.paid_at,
                "barcode": b.barcode or "",
                "digitable_line": b.digitable_line or "",
                "nota_fiscal_id": b.nota_fiscal_id,
                "nota_fiscal": (
                    {
                        "id": nf.id,
                        "numero": nf.numero,
                        "fornecedor": nf.fornecedor or "",
                        "amount": float(nf.amount or 0.0),
                    }
                    if nf
                    else None
                ),
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
            "notas": notas_ui,
        },
    )


@router.post("/cadastro/create")
def boletos_cadastro_create(
    competence: str = Form(...),
    beneficiario: str = Form(...),
    descricao: str = Form(""),
    due_date: str = Form(""),
    amount: float = Form(...),
    status: str = Form("A_VENCER"),
    nota_fiscal_id: str = Form(""),
    barcode: str = Form(""),
    digitable_line: str = Form(""),
    notes: str = Form(""),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    due = datetime.date.fromisoformat(due_date) if due_date.strip() else None
    nf_id = int(nota_fiscal_id) if (nota_fiscal_id or "").strip().isdigit() else None
    st = _norm_status_pagar(status)

    b = BoletoAPagar(
        competence_month=competence,
        beneficiario=beneficiario.strip(),
        descricao=(descricao.strip() or None),
        due_date=due,
        amount=float(amount),
        status=st,
        paid_at=(datetime.date.today() if st == "PAGO" else None),
        nota_fiscal_id=nf_id,
        barcode=(barcode.strip() or None),
        digitable_line=(digitable_line.strip() or None),
        notes=(notes.strip() or None),
    )
    db.add(b)
    db.commit()
    db.refresh(b)

    # Se já cadastrar como PAGO, já cria SAÍDA no financeiro da competência.
    if st == "PAGO":
        tag = f"AUTO:BOLETO_APAGAR:{b.id}"
        existing = db.query(LedgerEntry).filter(LedgerEntry.notes == tag).first()
        if not existing:
            desc = f"Boleto pago: {b.beneficiario}"
            if b.descricao:
                desc = f"{desc} — {b.descricao}"
            if b.nota_fiscal_id:
                desc = f"{desc} (NF #{b.nota_fiscal_id})"
            create_entry(
                db,
                competence=b.competence_month,
                entry_date=b.paid_at or datetime.date.today(),
                kind="SAIDA",
                amount=float(b.amount or 0.0),
                description=desc,
                status="REALIZADO",
                category="BOLETOS",
                notes=tag,
            )
    return _redirect_cadastro(competence)


@router.post("/cadastro/{boleto_id}/status")
def boletos_cadastro_update_status(
    boleto_id: int,
    competence: str = Form(...),
    status: str = Form(...),
    return_to: str = Form(""),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    b = db.query(BoletoAPagar).get(boleto_id)
    if b:
        st = _norm_status_pagar(status)
        b.status = st
        # Sincroniza paid_at
        if st == "PAGO" and b.paid_at is None:
            b.paid_at = datetime.date.today()
        if st != "PAGO":
            b.paid_at = None

        # Integra com o financeiro: ao marcar como PAGO, cria SAÍDA REALIZADA.
        # Ao desmarcar, remove o lançamento automático correspondente.
        tag = f"AUTO:BOLETO_APAGAR:{b.id}"
        existing = (
            db.query(LedgerEntry)
            .filter(LedgerEntry.notes == tag)
            .order_by(LedgerEntry.id.desc())
            .all()
        )

        if st == "PAGO":
            if not existing:
                desc = f"Boleto pago: {b.beneficiario}"
                if b.descricao:
                    desc = f"{desc} — {b.descricao}"
                if b.nota_fiscal_id:
                    desc = f"{desc} (NF #{b.nota_fiscal_id})"
                create_entry(
                    db,
                    competence=b.competence_month,
                    entry_date=b.paid_at or datetime.date.today(),
                    kind="SAIDA",
                    amount=float(b.amount or 0.0),
                    description=desc,
                    status="REALIZADO",
                    category="BOLETOS",
                    notes=tag,
                )
        else:
            for ent in existing:
                db.delete(ent)
        db.commit()
    return _redirect_back_or(f"/boletos/cadastro?competence={competence}", return_to)


@router.post("/cadastro/{boleto_id}/delete")
def boletos_cadastro_delete(
    boleto_id: int,
    competence: str = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    b = db.query(BoletoAPagar).get(boleto_id)
    if b:
        db.delete(b)
        db.commit()
    return _redirect_cadastro(competence)


# === BOLETOS A RECEBER (CADASTRO MANUAL) ===


@router.get("/receber-cadastro")
def boletos_receber_cadastro_page(
    request: Request,
    competence: str,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    import datetime as _dt

    ensure_boletos_receber_schema(db)

    company_emails = _load_company_emails()
    companies = (
        db.query(RateioCompany)
        .filter(RateioCompany.active == True)
        .order_by(RateioCompany.name.asc())
        .all()
    )
    companies_ui = [{"id": c.id, "name": c.name, "email": (company_emails.get(str(c.id)) or "")} for c in companies]

    rows = (
        db.query(BoletoAReceber)
        .filter(BoletoAReceber.competence_month == competence)
        .order_by(BoletoAReceber.id.desc())
        .all()
    )

    today = _dt.date.today()
    items = []
    for b in rows:
        st = (b.status or "A_VENCER").upper().strip()
        is_paid = st == "PAGO"
        due = b.due_date
        overdue = bool(due and (not is_paid) and (due < today))
        due_soon = bool(due and (not is_paid) and (0 <= (due - today).days <= 5))
        nf = b.nota_fiscal
        items.append(
            {
                "id": b.id,
                "customer_name": b.customer_name,
                "customer_email": b.customer_email,
                "description": b.description or "",
                "nota_fiscal_id": b.nota_fiscal_id,
                "nota_fiscal": (
                    {
                        "id": nf.id,
                        "numero": nf.numero,
                        "fornecedor": nf.fornecedor or "",
                        "amount": float(nf.amount or 0.0),
                    }
                    if nf
                    else None
                ),
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
                "due_date": (b.due_date or inst.due_date),
                "amount": float(b.amount or inst.amount or rec.amount or 0.0),
                "description": (rec.description or ""),
                "nosso_numero": b.nosso_numero or "",
                "digitable_line": b.digitable_line or "",
                "status": status_norm,
            }
        )

    notas = (
        db.query(NotaFiscal)
        .filter(NotaFiscal.competence_month == competence)
        .order_by(NotaFiscal.id.desc())
        .all()
    )
    notas_ui = [
        {
            "id": n.id,
            "numero": n.numero,
            "fornecedor": n.fornecedor or "",
            "amount": float(n.amount or 0.0),
        }
        for n in notas
    ]

    return templates.TemplateResponse(
        "boletos/receber_cadastro.html",
        {
            "request": request,
            "user": user,
            "competence": competence,
            "items": items,
            "companies": companies_ui,
            "linked_boletos": linked_boletos,
            "notas": notas_ui,
        },
    )


@router.post("/receber-cadastro/create")
def boletos_receber_cadastro_create(
    competence: str = Form(...),
    construtora_id: str = Form(""),
    source_boleto_id: str = Form(""),
    nota_fiscal_id: str = Form(""),
    customer_name: str = Form(...),
    customer_email: str = Form(""),
    description: str = Form(""),
    due_date: str = Form(""),
    amount: float = Form(...),
    status: str = Form("A_VENCER"),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    import datetime as _dt

    ensure_boletos_receber_schema(db)

    selected_company = None
    company_email = ""
    if (construtora_id or "").strip().isdigit():
        selected_company = (
            db.query(RateioCompany)
            .filter(RateioCompany.id == int(construtora_id))
            .first()
        )
        company_email = _load_company_emails().get(str(int(construtora_id)), "")

    resolved_name = (customer_name or "").strip() or ((selected_company.name if selected_company else "") or "")
    resolved_email = (customer_email or "").strip() or company_email
    resolved_desc = (description or "").strip() or None
    resolved_due = (_dt.date.fromisoformat(due_date) if (due_date or "").strip() else None)
    resolved_amount = float(amount or 0.0)
    resolved_status = (status or "A_VENCER").upper().strip()
    resolved_nf_id = int(nota_fiscal_id) if (nota_fiscal_id or "").strip().isdigit() else None

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
        customer_email=(resolved_email or None),
        description=resolved_desc,
        nota_fiscal_id=resolved_nf_id,
        due_date=resolved_due,
        amount=float(resolved_amount or 0.0),
        status=resolved_status,
    )
    if b.status == "PAGO":
        b.paid_at = _dt.datetime.utcnow()
    db.add(b)
    db.commit()
    db.refresh(b)

    # Se já cadastrou como PAGO, já lança no financeiro
    if (b.status or "").upper().strip() == "PAGO":
        tag = f"AUTO:BOLETO_RECEBER_CAD:{b.id}"
        existing = db.query(LedgerEntry).filter(LedgerEntry.notes == tag).first()
        if not existing:
            entry_date = (b.paid_at.date() if b.paid_at else _dt.date.today())
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

    return RedirectResponse(f"/boletos/receber-cadastro?competence={competence}", status_code=303)


@router.post("/receber-cadastro/{boleto_id}/status")
def boletos_receber_cadastro_update_status(
    boleto_id: int,
    competence: str = Form(...),
    status: str = Form(...),
    return_to: str = Form(""),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    import datetime as _dt

    ensure_boletos_receber_schema(db)

    b = db.query(BoletoAReceber).filter(BoletoAReceber.id == boleto_id).first()
    if not b:
        return _redirect_back_or(f"/boletos/receber-cadastro?competence={competence}", return_to)

    new_status = (status or "A_VENCER").upper().strip()
    b.status = new_status

    tag = f"AUTO:BOLETO_RECEBER_CAD:{b.id}"
    existing = db.query(LedgerEntry).filter(LedgerEntry.notes == tag).first()

    if new_status == "PAGO":
        if not b.paid_at:
            b.paid_at = _dt.datetime.utcnow()
        if not existing:
            desc = f"Recebimento boleto (cadastro) - {b.customer_name}"
            create_entry(
                db,
                competence=b.competence_month,
                entry_date=(b.paid_at.date() if b.paid_at else _dt.date.today()),
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
        # se não está pago, remove lançamento automático
        b.paid_at = None
        if existing:
            db.delete(existing)

    db.commit()
    return _redirect_back_or(f"/boletos/receber-cadastro?competence={competence}", return_to)


@router.post("/receber-cadastro/{boleto_id}/delete")
def boletos_receber_cadastro_delete(
    boleto_id: int,
    competence: str = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    ensure_boletos_receber_schema(db)

    b = db.query(BoletoAReceber).filter(BoletoAReceber.id == boleto_id).first()
    if b:
        # Remove lançamento automático, se existir
        tag = f"AUTO:BOLETO_RECEBER_CAD:{b.id}"
        existing = db.query(LedgerEntry).filter(LedgerEntry.notes == tag).first()
        if existing:
            db.delete(existing)
        db.delete(b)
        db.commit()

    return RedirectResponse(f"/boletos/receber-cadastro?competence={competence}", status_code=303)


@router.post("/receber-cadastro/{boleto_id}/email")
def boletos_receber_cadastro_update_email(
    boleto_id: int,
    competence: str = Form(...),
    customer_email: str = Form(""),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    ensure_boletos_receber_schema(db)

    b = db.query(BoletoAReceber).filter(BoletoAReceber.id == boleto_id).first()
    if b:
        b.customer_email = (customer_email.strip() or None)
        db.commit()
    return RedirectResponse(f"/boletos/receber-cadastro?competence={competence}", status_code=303)
