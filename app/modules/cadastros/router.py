from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from urllib.parse import quote_plus

from app.core.templating import templates
from app.core.deps import get_db
from app.modules.auth.utils import require_login
from app.models.customer import Customer
from app.core.audit import audit_log
from app.modules.lancamentos.service import (
    ensure_lookup_tables,
    sync_lookup_options_from_entries,
    list_category_options,
    list_cost_center_options,
    create_category_option,
    create_cost_center_option,
    rename_category_option,
    rename_cost_center_option,
    delete_category_option,
    delete_cost_center_option,
    category_usage_map,
    cost_center_usage_map,
)

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


@router.get("/lancamentos-opcoes")
def lancamentos_opcoes_page(
    request: Request,
    ok: str | None = None,
    error: str | None = None,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    ensure_lookup_tables(db)
    sync_lookup_options_from_entries(db)

    categories = list_category_options(db)
    cost_centers = list_cost_center_options(db)
    cat_usage = category_usage_map(db)
    cc_usage = cost_center_usage_map(db)

    return templates.TemplateResponse(
        "cadastros/lancamentos_opcoes.html",
        {
            "request": request,
            "user": user,
            "categories": categories,
            "cost_centers": cost_centers,
            "cat_usage": cat_usage,
            "cc_usage": cc_usage,
            "ok": ok,
            "error": error,
        },
    )


@router.post("/lancamentos-opcoes/categorias")
def lancamentos_opcoes_categoria_create(
    name: str = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    ensure_lookup_tables(db)
    item = create_category_option(db, name)
    if not item:
        msg = quote_plus("Informe uma categoria valida")
        return RedirectResponse(f"/cadastros/lancamentos-opcoes?error={msg}", status_code=303)
    msg = quote_plus("Categoria salva com sucesso")
    return RedirectResponse(f"/cadastros/lancamentos-opcoes?ok={msg}", status_code=303)


@router.post("/lancamentos-opcoes/categorias/{option_id}/edit")
def lancamentos_opcoes_categoria_edit(
    option_id: int,
    name: str = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    ensure_lookup_tables(db)
    _, err = rename_category_option(db, option_id, name)
    if err:
        msg = quote_plus(err)
        return RedirectResponse(f"/cadastros/lancamentos-opcoes?error={msg}", status_code=303)
    msg = quote_plus("Categoria atualizada")
    return RedirectResponse(f"/cadastros/lancamentos-opcoes?ok={msg}", status_code=303)


@router.post("/lancamentos-opcoes/categorias/{option_id}/delete")
def lancamentos_opcoes_categoria_delete(
    option_id: int,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    ensure_lookup_tables(db)
    ok = delete_category_option(db, option_id)
    if not ok:
        msg = quote_plus("Categoria nao encontrada")
        return RedirectResponse(f"/cadastros/lancamentos-opcoes?error={msg}", status_code=303)
    msg = quote_plus("Categoria excluida")
    return RedirectResponse(f"/cadastros/lancamentos-opcoes?ok={msg}", status_code=303)


@router.post("/lancamentos-opcoes/centros-custo")
def lancamentos_opcoes_cost_center_create(
    name: str = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    ensure_lookup_tables(db)
    item = create_cost_center_option(db, name)
    if not item:
        msg = quote_plus("Informe um centro de custo valido")
        return RedirectResponse(f"/cadastros/lancamentos-opcoes?error={msg}", status_code=303)
    msg = quote_plus("Centro de custo salvo com sucesso")
    return RedirectResponse(f"/cadastros/lancamentos-opcoes?ok={msg}", status_code=303)


@router.post("/lancamentos-opcoes/centros-custo/{option_id}/edit")
def lancamentos_opcoes_cost_center_edit(
    option_id: int,
    name: str = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    ensure_lookup_tables(db)
    _, err = rename_cost_center_option(db, option_id, name)
    if err:
        msg = quote_plus(err)
        return RedirectResponse(f"/cadastros/lancamentos-opcoes?error={msg}", status_code=303)
    msg = quote_plus("Centro de custo atualizado")
    return RedirectResponse(f"/cadastros/lancamentos-opcoes?ok={msg}", status_code=303)


@router.post("/lancamentos-opcoes/centros-custo/{option_id}/delete")
def lancamentos_opcoes_cost_center_delete(
    option_id: int,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    ensure_lookup_tables(db)
    ok = delete_cost_center_option(db, option_id)
    if not ok:
        msg = quote_plus("Centro de custo nao encontrado")
        return RedirectResponse(f"/cadastros/lancamentos-opcoes?error={msg}", status_code=303)
    msg = quote_plus("Centro de custo excluido")
    return RedirectResponse(f"/cadastros/lancamentos-opcoes?ok={msg}", status_code=303)
