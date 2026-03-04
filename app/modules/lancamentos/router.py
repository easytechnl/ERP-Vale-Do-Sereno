from datetime import date
import calendar
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.templating import templates
from app.core.utils import normalize_competence
from app.modules.auth.utils import require_login
from app.models.customer import Customer
from app.modules.lancamentos.service import (
    list_entries,
    create_entry,
    delete_entry,
    ensure_lookup_tables,
    sync_lookup_options_from_entries,
    list_category_options,
    list_cost_center_options,
    create_category_option,
    create_cost_center_option,
)


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
    new_category: str | None = None,
    new_cost_center: str | None = None,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    if not competence:
        competence = date.today().strftime("%Y-%m")

    competence = normalize_competence(competence) or competence

    ensure_lookup_tables(db)
    sync_lookup_options_from_entries(db)

    entries = list_entries(
        db,
        competence=competence,
        kind=kind,
        status=status,
        bank_account_id=bank_account_id,
        customer_id=customer_id,
        q=q,
    )

    customers = db.query(Customer).order_by(Customer.name.asc()).all()
    categories = list_category_options(db)
    cost_centers = list_cost_center_options(db)

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
            "customers": customers,
            "categories": categories,
            "cost_centers": cost_centers,
            "filters": {
                "kind": kind,
                "status": status,
                "customer_id": customer_id,
                "q": q,
            },
            "new_entry_defaults": {
                "category": (new_category or "").strip(),
                "cost_center": (new_cost_center or "").strip(),
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
    document_number: str | None = Form(None),
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

    ensure_lookup_tables(db)
    category = (category or "").strip() or None
    cost_center = (cost_center or "").strip() or None
    document_number = (document_number or "").strip() or None
    if category:
        create_category_option(db, category)
    if cost_center:
        create_cost_center_option(db, cost_center)

    d0 = date.fromisoformat(entry_date)

    # cria o lançamento principal
    create_entry(
        db,
        competence=competence,
        entry_date=d0,
        kind=kind,
        amount=amount,
        description=description,
        document_number=document_number,
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
                document_number=document_number,
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
                    document_number=document_number,
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


@router.post("/categorias/nova")
def lancamentos_new_category(
    competence: str = Form(...),
    name: str = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = normalize_competence(competence) or competence
    ensure_lookup_tables(db)
    item = create_category_option(db, name)
    selected = quote(item.name) if item else ""
    return RedirectResponse(
        url=f"/lancamentos?competence={competence}&new_category={selected}#novo",
        status_code=303,
    )


@router.post("/centros-custo/novo")
def lancamentos_new_cost_center(
    competence: str = Form(...),
    name: str = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = normalize_competence(competence) or competence
    ensure_lookup_tables(db)
    item = create_cost_center_option(db, name)
    selected = quote(item.name) if item else ""
    return RedirectResponse(
        url=f"/lancamentos?competence={competence}&new_cost_center={selected}#novo",
        status_code=303,
    )
