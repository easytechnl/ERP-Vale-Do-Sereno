from __future__ import annotations

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.templating import templates
from app.core.deps import get_db
from app.modules.auth.utils import require_login

from app.models.rateio import RateioCompany, RateioExpense

from .service import (
    get_percentual_docx_path,
    ensure_companies_seeded_from_docx,
    compute_divisao_custos,
    compute_company_breakdown,
)
from .pdf import generate_company_cost_division_pdf_bytes


router = APIRouter(tags=["divisao_custos"])


def _redirect_back(competence: str | None) -> RedirectResponse:
    url = "/divisao-custos" + (f"?competence={competence}" if competence else "")
    return RedirectResponse(url=url, status_code=303)


@router.get("/rateio")
@router.get("/rateio/")
def legacy_rateio_redirect(competence: str | None = None, user=Depends(require_login)):
    """Compatibilidade: rota antiga /rateio -> /divisao-custos."""
    url = "/divisao-custos" + (f"?competence={competence}" if competence else "")
    return RedirectResponse(url=url, status_code=302)


@router.get("/divisao-custos")
@router.get("/divisao-custos/")
def divisao_custos_page(
    request: Request,
    competence: str | None = None,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    import datetime
    import logging

    log = logging.getLogger("divisao_custos")

    competence = competence or datetime.date.today().strftime("%Y-%m")

    # Sincroniza construtoras/percentuais conforme DOCX base
    docx_path = get_percentual_docx_path()
    file_error: str | None = None
    if docx_path.exists():
        try:
            changed, total_pct = ensure_companies_seeded_from_docx(db, docx_path)
            if changed:
                log.info("Divisão de Custos: %s alterações ao sincronizar do DOCX (total_pct=%.6f)", changed, total_pct)
        except Exception as e:
            log.exception("Falha ao sincronizar construtoras do DOCX")
            file_error = f"Não consegui sincronizar construtoras do arquivo de percentuais (DOCX): {e}"
    else:
        file_error = "Arquivo base de percentuais não encontrado em app/assets/percentual.docx"

    preview = compute_divisao_custos(db=db, competence=competence)

    # Lista construtoras cadastradas
    companies = (
        db.query(RateioCompany)
        .filter(RateioCompany.active == True)  # noqa: E712
        .order_by(RateioCompany.name.asc())
        .all()
    )

    companies_ui = [
        {
            "id": c.id,
            "name": c.name,
            "legal_name": c.legal_name or "",
            "cnpj": c.cnpj or "",
            "area_m2": float(c.area_m2) if c.area_m2 is not None else 0.0,
            "percentual": float(c.percentual) if c.percentual is not None else 0.0,
            "notes": c.notes or "",
        }
        for c in companies
    ]

    # Enriquecer com valores calculados
    by_id = {int(r.get("id")): r for r in (preview.get("companies") or []) if r.get("id") is not None}
    for cu in companies_ui:
        r = by_id.get(int(cu["id"]))
        if r:
            cu["valor_a_pagar"] = float(r.get("total") or 0.0)
            cu["percentual_used"] = float(r.get("percentual") or 0.0)
            cu["missing_percentual"] = bool(r.get("missing_percentual"))
        else:
            cu["valor_a_pagar"] = 0.0
            cu["percentual_used"] = float(cu.get("percentual") or 0.0)
            cu["missing_percentual"] = not bool(cu.get("percentual") or 0.0)

    return templates.TemplateResponse(
        "rateio/divisao_custos.html",
        {
            "request": request,
            "user": user,
            "competence": competence,
            "file_error": file_error,
            "preview": preview,
            "companies": companies_ui,
            "percentual_source": "Base oficial (DOCX) — EasyTech",
            "percentual_file_name": docx_path.name,
        },
    )


@router.post("/divisao-custos/despesas")
def despesas_create(
    request: Request,
    competence: str = Form(...),
    description: str = Form(...),
    category: str = Form(""),
    amount: float = Form(...),
    expense_date: str = Form(""),  # YYYY-MM-DD (opcional)
    recurrence_months: int = Form(0),
    end_date: str = Form(""),
    notes: str = Form(""),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    import datetime

    # Se o usuário não informar data base, assumimos 1o dia da competência
    if not expense_date.strip():
        y, m = [int(x) for x in competence.split("-")]
        exp_dt = datetime.date(y, m, 1)
    else:
        exp_dt = datetime.date.fromisoformat(expense_date)

    e = RateioExpense(
        description=description.strip(),
        category=(category.strip() or None),
        amount=float(amount),
        expense_date=exp_dt,
        recurrence_months=int(recurrence_months or 0),
        end_date=(datetime.date.fromisoformat(end_date) if end_date.strip() else None),
        notes=(notes.strip() or None),
        active=True,
    )
    db.add(e)
    db.commit()
    return _redirect_back(competence)


@router.post("/divisao-custos/despesas/{expense_id}/delete")
def despesas_delete(
    expense_id: int,
    competence: str = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    e = db.query(RateioExpense).get(expense_id)
    if e:
        db.delete(e)
        db.commit()
    return _redirect_back(competence)


@router.post("/divisao-custos/construtoras")
def construtoras_create(
    request: Request,
    competence: str = Form(...),
    name: str = Form(...),
    legal_name: str = Form(""),
    cnpj: str = Form(""),
    area_m2: str = Form(""),
    percentual: str = Form(""),
    notes: str = Form(""),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    # Cadastro manual (mantém para novas construtoras)
    area_val = float(area_m2) if area_m2.strip() else None
    # Aceita 0,12 / 0.12 / 12 / 12% (salva sempre como FRAÇÃO)
    pct_val = None
    if percentual.strip():
        raw = percentual.strip().replace(" ", "")
        raw = raw.replace("%", "")
        raw = raw.replace(",", ".")
        try:
            pct_val = float(raw)
            if pct_val > 1:
                pct_val = pct_val / 100.0
        except Exception:
            pct_val = None

    c = RateioCompany(
        name=name.strip(),
        legal_name=(legal_name.strip() or None),
        cnpj=(cnpj.strip() or None),
        area_m2=area_val,
        percentual=pct_val,
        notes=(notes.strip() or None),
        active=True,
    )
    db.add(c)
    db.commit()
    return _redirect_back(competence)


@router.post("/divisao-custos/construtoras/{company_id}/delete")
def construtoras_delete(
    company_id: int,
    competence: str = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    c = db.query(RateioCompany).get(company_id)
    if c:
        db.delete(c)
        db.commit()
    return _redirect_back(competence)


@router.get("/divisao-custos/pdf/{company_id}")
def company_pdf(
    company_id: int,
    competence: str,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    """Gera o PDF individual (demonstração de custos) de uma construtora."""

    import io

    # garante sync (caso suba versão nova do DOCX)
    docx_path = get_percentual_docx_path()
    if docx_path.exists():
        ensure_companies_seeded_from_docx(db, docx_path)

    preview = compute_divisao_custos(db=db, competence=competence)
    data = compute_company_breakdown(preview, company_id)
    if not data:
        return StreamingResponse(iter([b"Construtora nao encontrada"]))

    company = data["company"]
    breakdown = data["breakdown"]

    pdf_bytes = generate_company_cost_division_pdf_bytes(
        association_name="Associação Vale do Sereno",
        competence=competence,
        total_despesas=float(preview.get("total_despesas") or 0.0),
        despesas_breakdown=breakdown,
        company=company,
        total_company=float(data.get("total_company") or 0.0),
        footer_brand="Desenvolvido EasyTech — Facilitando a tecnologia",
    )

    filename = f"divisao_custos_{competence}_{company.get('name','construtora')}.pdf".replace(" ", "_")
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/divisao-custos/pdfs.zip")
def all_pdfs_zip(
    competence: str,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    """Gera um ZIP com um PDF por construtora (demonstração de custos)."""

    import io
    import zipfile

    docx_path = get_percentual_docx_path()
    if docx_path.exists():
        ensure_companies_seeded_from_docx(db, docx_path)

    preview = compute_divisao_custos(db=db, competence=competence)

    mem = io.BytesIO()
    with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for r in preview.get("companies") or []:
            cid = int(r.get("id") or 0)
            data = compute_company_breakdown(preview, cid)
            if not data:
                continue
            company = data["company"]
            breakdown = data["breakdown"]
            pdf_bytes = generate_company_cost_division_pdf_bytes(
                association_name="Associação Vale do Sereno",
                competence=competence,
                total_despesas=float(preview.get("total_despesas") or 0.0),
                despesas_breakdown=breakdown,
                company=company,
                total_company=float(data.get("total_company") or 0.0),
                footer_brand="Desenvolvido EasyTech — Facilitando a tecnologia",
            )
            safe_name = (company.get("name") or "construtora").replace("/", "-").replace("\\", "-").replace(" ", "_")
            fn = f"divisao_custos_{competence}_{safe_name}.pdf"
            zf.writestr(fn, pdf_bytes)

    mem.seek(0)
    filename = f"divisao_custos_pdfs_{competence}.zip"
    return StreamingResponse(mem, media_type="application/zip", headers={"Content-Disposition": f"attachment; filename={filename}"})


