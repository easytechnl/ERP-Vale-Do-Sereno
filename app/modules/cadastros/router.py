from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

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
