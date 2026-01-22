from datetime import date
import calendar

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.templating import templates
from app.core.utils import normalize_competence
from app.modules.auth.utils import require_login
from app.models.bancos import BankAccount
from app.models.customer import Customer
from app.modules.lancamentos.service import list_entries, create_entry, delete_entry


router = APIRouter(prefix="/lancamentos", tags=["lancamentos"])


@router.get("")
def lancamentos_page(
    request: Request,
    competence: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    bank_account_id: int | None = None,
    customer_id: int | None = None,
    q: str | None = None,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    if not competence:
        competence = date.today().strftime("%Y-%m")

    competence = normalize_competence(competence) or competence

    entries = list_entries(
        db,
        competence=competence,
        kind=kind,
        status=status,
        bank_account_id=bank_account_id,
        customer_id=customer_id,
        q=q,
    )

    accounts = (
        db.query(BankAccount)
        .filter(BankAccount.is_active == True)  # noqa: E712
        .order_by(BankAccount.name.asc())
        .all()
    )
    customers = db.query(Customer).order_by(Customer.name.asc()).all()

    entradas = sum(float(x.amount) for x in entries if x.kind == "ENTRADA")
    saidas = sum(float(x.amount) for x in entries if x.kind == "SAIDA")
    saldo = entradas - saidas

    return templates.TemplateResponse(
        "lancamentos/lancamentos.html",
        {
            "request": request,
            "user": user,
            "competence": competence,
            "entries": entries,
            "accounts": accounts,
            "customers": customers,
            "filters": {
                "kind": kind,
                "status": status,
                "bank_account_id": bank_account_id,
                "customer_id": customer_id,
                "q": q,
            },
            "totals": {"entradas": entradas, "saidas": saidas, "saldo": saldo},
        },
    )


@router.post("/novo")
def lancamentos_create(
    competence: str = Form(...),
    entry_date: str = Form(...),
    kind: str = Form(...),
    amount: float = Form(...),
    description: str = Form(...),
    status: str = Form("REALIZADO"),
    category: str | None = Form(None),
    cost_center: str | None = Form(None),
    bank_account_id: int | None = Form(None),
    customer_id: int | None = Form(None),
    notes: str | None = Form(None),
    repeat_extra_months: int = Form(0),
    repeat_until: str | None = Form(None),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    def add_months(dt: date, months: int) -> date:
        y = dt.year + (dt.month - 1 + months) // 12
        m = (dt.month - 1 + months) % 12 + 1
        last_day = calendar.monthrange(y, m)[1]
        day = min(dt.day, last_day)
        return date(y, m, day)

    competence = normalize_competence(competence) or competence

    d0 = date.fromisoformat(entry_date)

    # cria o lançamento principal
    create_entry(
        db,
        competence=competence,
        entry_date=d0,
        kind=kind,
        amount=amount,
        description=description,
        status=status,
        category=category,
        cost_center=cost_center,
        bank_account_id=bank_account_id,
        customer_id=customer_id,
        notes=notes,
    )

    # recorrência (mensal) — cria lançamentos nas competências futuras
    end_date: date | None = None
    if repeat_until:
        try:
            end_date = date.fromisoformat(repeat_until)
        except Exception:
            end_date = None

    if end_date and end_date > d0:
        i = 1
        while True:
            di = add_months(d0, i)
            if di > end_date:
                break
            ci = di.strftime("%Y-%m")
            create_entry(
                db,
                competence=ci,
                entry_date=di,
                kind=kind,
                amount=amount,
                description=description,
                status=status,
                category=category,
                cost_center=cost_center,
                bank_account_id=bank_account_id,
                customer_id=customer_id,
                notes=notes,
            )
            i += 1
    else:
        extra = int(repeat_extra_months or 0)
        if extra > 0:
            for i in range(1, extra + 1):
                di = add_months(d0, i)
                ci = di.strftime("%Y-%m")
                create_entry(
                    db,
                    competence=ci,
                    entry_date=di,
                    kind=kind,
                    amount=amount,
                    description=description,
                    status=status,
                    category=category,
                    cost_center=cost_center,
                    bank_account_id=bank_account_id,
                    customer_id=customer_id,
                    notes=notes,
                )
    return RedirectResponse(url=f"/lancamentos?competence={competence}", status_code=303)


@router.post("/{entry_id}/delete")
def lancamentos_delete(
    entry_id: int,
    competence: str = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    delete_entry(db, entry_id)
    return RedirectResponse(url=f"/lancamentos?competence={competence}", status_code=303)
