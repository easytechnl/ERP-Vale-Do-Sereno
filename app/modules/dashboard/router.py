from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.templating import templates
from app.core.utils import clamp_competence, current_competence, supported_competence
from app.models.conciliacao import BankStatementImport
from app.models.saldo import BalanceAdjustment
from app.modules.auth.utils import require_login
from app.modules.conciliacao.service import statement_totals_for_competence
from app.modules.lancamentos.service import totals_for_period
from app.modules.relatorios.service import get_or_create_monthly_close

router = APIRouter()


@router.get("/")
def home(request: Request, competence: str | None = None, user=Depends(require_login), db: Session = Depends(get_db)):
    last_imp = db.query(BankStatementImport).order_by(BankStatementImport.id.desc()).first()
    default_competence = supported_competence(getattr(last_imp, "competence_month", None)) or current_competence()
    competence = clamp_competence(competence, fallback=default_competence) or current_competence()

    close = get_or_create_monthly_close(db, competence)

    stmt = statement_totals_for_competence(db, competence)
    ledger = totals_for_period(db, start_ym=competence, end_ym=competence, status="REALIZADO")

    totals = {
        "entradas": float(stmt.get("entradas") or 0.0) + float(ledger.get("entradas") or 0.0),
        "saidas": float(stmt.get("saidas") or 0.0) + float(ledger.get("saidas") or 0.0),
        "saldo": (float(stmt.get("entradas") or 0.0) + float(ledger.get("entradas") or 0.0))
        - (float(stmt.get("saidas") or 0.0) + float(ledger.get("saidas") or 0.0)),
    }

    if stmt.get("has_statement") and (ledger.get("entradas") or 0.0 or ledger.get("saidas") or 0.0):
        totals_source = "OFX + LANCAMENTOS"
    elif stmt.get("has_statement"):
        totals_source = "OFX"
    else:
        totals_source = "LANCAMENTOS"

    statement_meta = (
        {
            "transactions": int(stmt.get("transactions") or 0),
            "imported_at": getattr(stmt.get("last_import"), "imported_at", None),
            "file_path": getattr(stmt.get("last_import"), "file_path", None),
        }
        if stmt.get("has_statement")
        else None
    )

    balance_adj = float(
        db.query(func.coalesce(func.sum(BalanceAdjustment.amount), 0))
        .filter(BalanceAdjustment.competence_month == competence)
        .scalar()
        or 0.0
    )
    if balance_adj:
        totals["saldo"] = float(totals.get("saldo") or 0.0) + balance_adj

    return templates.TemplateResponse(
        "dashboard/home.html",
        {
            "request": request,
            "user": user,
            "competence": competence,
            "close": close,
            "totals": totals,
            "totals_source": totals_source,
            "statement_meta": statement_meta,
            "balance_adj": balance_adj,
        },
    )


@router.post("/dashboard/saldo/add")
def add_balance_adjustment(
    competence: str = Form(...),
    amount: float = Form(...),
    note: str | None = Form(None),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = clamp_competence(competence) or competence
    adj = BalanceAdjustment(competence_month=competence, amount=amount, note=note)
    db.add(adj)
    db.commit()
    return RedirectResponse(f"/?competence={competence}", status_code=303)


@router.post("/dashboard/saldo/delete")
def delete_balance_adjustment(
    competence: str = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = clamp_competence(competence) or competence
    db.query(BalanceAdjustment).filter(BalanceAdjustment.competence_month == competence).delete(synchronize_session=False)
    db.commit()
    return RedirectResponse(f"/?competence={competence}", status_code=303)
