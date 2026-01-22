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
from app.modules.boletos.service import generate_boletos_for_competence, generate_cnab_remittance, import_cnab_return

router = APIRouter(prefix="/boletos", tags=["boletos"])


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
    b.status = status

    # mantém parcela sincronizada com o status do boleto
    inst = db.query(Installment).filter(Installment.id == b.installment_id).first()
    if inst:
        st = (status or "").upper()
        if "PAG" in st or "BAIX" in st:
            inst.status = "BAIXADA"
        elif "CANC" in st:
            inst.status = "CANCELADA"
        else:
            inst.status = "ABERTA"
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
