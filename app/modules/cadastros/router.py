from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.templating import templates
from app.core.deps import get_db
from app.modules.auth.utils import require_login
from app.models.customer import Customer
from app.core.audit import audit_log

router = APIRouter(prefix="/cadastros", tags=["cadastros"])

@router.get("/clientes")
def clientes_list(request: Request, user=Depends(require_login), db: Session = Depends(get_db)):
    clientes = db.query(Customer).order_by(Customer.name.asc()).all()
    return templates.TemplateResponse("cadastros/clientes.html", {"request": request, "user": user, "clientes": clientes})

@router.post("/clientes")
def clientes_create(
    request: Request,
    name: str = Form(...),
    cpf_cnpj: str = Form("",),
    email: str = Form("",),
    address: str = Form("",),
    notes: str = Form("",),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    c = Customer(
        name=name.strip(),
        cpf_cnpj=(cpf_cnpj.strip() or None),
        email=(email.strip() or None),
        address=(address.strip() or None),
        notes=(notes.strip() or None),
        active=True
    )
    db.add(c)
    audit_log(db, user.id, "Customer", None, "CREATE", after={"name": c.name, "cpf_cnpj": c.cpf_cnpj, "email": c.email})
    db.commit()
    return RedirectResponse("/cadastros/clientes", status_code=303)


@router.post("/clientes/{customer_id}/toggle")
def clientes_toggle_active(
    customer_id: int,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    c = db.query(Customer).filter(Customer.id == customer_id).first()
    if not c:
        return RedirectResponse("/cadastros/clientes", status_code=303)

    before = {"active": bool(c.active)}
    c.active = not bool(c.active)
    audit_log(db, user.id, "Customer", c.id, "UPDATE", before=before, after={"active": bool(c.active)})
    db.commit()
    return RedirectResponse("/cadastros/clientes", status_code=303)


@router.post("/clientes/{customer_id}/delete")
def clientes_delete(
    customer_id: int,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    c = db.query(Customer).filter(Customer.id == customer_id).first()
    if not c:
        return RedirectResponse("/cadastros/clientes", status_code=303)

    # tenta excluir; se houver vínculo (receivables), faz desativação como fallback
    try:
        audit_log(db, user.id, "Customer", c.id, "DELETE", before={"name": c.name, "cpf_cnpj": c.cpf_cnpj, "email": c.email})
        db.delete(c)
        db.commit()
    except IntegrityError:
        db.rollback()
        before = {"active": bool(c.active)}
        c.active = False
        audit_log(db, user.id, "Customer", c.id, "UPDATE", before=before, after={"active": False, "note": "Auto-desativado (possui vínculos)"})
        db.commit()

    return RedirectResponse("/cadastros/clientes", status_code=303)
