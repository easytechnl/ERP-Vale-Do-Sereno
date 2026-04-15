from __future__ import annotations

import io
import json
from pathlib import Path
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.templating import templates
from app.core.deps import get_db
from app.core.ui_feedback import toast_redirect, with_query_params
from app.core.utils import clamp_competence, current_competence
from app.modules.auth.utils import require_login

from app.models.boletos_receber import BoletoAReceber
from app.models.rateio import RateioCompany, RateioExpense

from .service import (
    get_percentual_docx_path,
    ensure_companies_seeded_from_docx,
    compute_divisao_custos,
    compute_company_breakdown,
)
from .pdf import generate_company_cost_division_pdf_bytes
from .pdf_summary import generate_rateio_summary_pdf_bytes


router = APIRouter(tags=["divisao_custos"])
SETTINGS_PATH = Path("data/configuracoes.json")


def _divisao_custos_url(competence: str | None) -> str:
    return "/divisao-custos" + (f"?competence={competence}" if competence else "")


def _redirect_back(competence: str | None) -> RedirectResponse:
    return RedirectResponse(url=_divisao_custos_url(competence), status_code=303)


def _parse_optional_number(raw: str, *, field_label: str) -> tuple[float | None, str | None]:
    value = (raw or "").strip()
    if not value:
        return None, None

    normalized = value.replace(" ", "")
    if "," in normalized and "." in normalized and normalized.find(",") > normalized.find("."):
        normalized = normalized.replace(".", "")
    normalized = normalized.replace(",", ".")

    try:
        return float(normalized), None
    except ValueError:
        return None, f"Informe um valor numérico válido para {field_label}."


def _parse_percentual_input(raw: str) -> tuple[float | None, str | None]:
    value = (raw or "").strip()
    if not value:
        return None, None

    normalized = value.replace(" ", "").replace("%", "")
    if "," in normalized and "." in normalized and normalized.find(",") > normalized.find("."):
        normalized = normalized.replace(".", "")
    normalized = normalized.replace(",", ".")

    try:
        pct = float(normalized)
    except ValueError:
        return None, "Informe um percentual válido."

    if pct > 1:
        pct = pct / 100.0
    return float(pct), None


def _last_day_of_competence(competence: str):
    import datetime as _dt

    y, m = [int(x) for x in competence.split("-")[:2]]
    if m == 12:
        next_month = _dt.date(y + 1, 1, 1)
    else:
        next_month = _dt.date(y, m + 1, 1)
    return next_month - _dt.timedelta(days=1)


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


@router.get("/rateio")
@router.get("/rateio/")
def legacy_rateio_redirect(competence: str | None = None, user=Depends(require_login)):
    """Compatibilidade: rota antiga /rateio -> /divisao-custos."""
    competence = clamp_competence(competence, fallback=current_competence()) if competence else None
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

    competence = clamp_competence(competence, fallback=current_competence()) or current_competence()

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
            cu["valor_base"] = float(r.get("valor_base") or r.get("base") or 0.0)
            cu["reserva"] = float(r.get("reserva") or 0.0)
            cu["valor_a_pagar"] = float(r.get("total") or 0.0)
            cu["percentual_used"] = float(r.get("percentual") or 0.0)
            cu["missing_percentual"] = bool(r.get("missing_percentual"))
        else:
            cu["valor_base"] = 0.0
            cu["reserva"] = 0.0
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

    competence = clamp_competence(competence) or competence
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
    return toast_redirect(_divisao_custos_url(competence))


@router.post("/divisao-custos/despesas/{expense_id}/delete")
def despesas_delete(
    expense_id: int,
    competence: str = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = clamp_competence(competence) or competence
    e = db.query(RateioExpense).get(expense_id)
    if e:
        db.delete(e)
        db.commit()
        return toast_redirect(_divisao_custos_url(competence))
    return toast_redirect(
        _divisao_custos_url(competence),
        kind="err",
        message="Despesa não encontrada.",
    )


@router.post("/divisao-custos/salvar")
def gerar_boletos_receber_da_divisao(
    competence: str = Form(...),
    due_date: str = Form(""),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    import datetime as _dt

    competence = clamp_competence(competence) or competence
    preview = compute_divisao_custos(db=db, competence=competence)
    companies = preview.get("companies") or []
    if not companies:
        return toast_redirect(
            with_query_params(_divisao_custos_url(competence), gerar_boletos="empty"),
            kind="err",
            message="Nenhuma construtora elegível para gerar contas a receber.",
        )

    resolved_due_date = _last_day_of_competence(competence)
    if (due_date or "").strip():
        try:
            resolved_due_date = _dt.date.fromisoformat(due_date.strip())
        except Exception:
            pass

    company_emails = _load_company_emails()
    auto_description = f"Divisão de Custos ({competence})"

    created = 0
    updated = 0
    skipped = 0

    for company in companies:
        company_id = int(company.get("id") or 0)
        company_name = str(company.get("name") or "").strip()
        amount = float(company.get("total") or 0.0)
        if company_id <= 0 or not company_name or amount <= 0:
            skipped += 1
            continue

        email = (company_emails.get(str(company_id)) or "").strip() or None

        existing = (
            db.query(BoletoAReceber)
            .filter(BoletoAReceber.competence_month == competence)
            .filter(BoletoAReceber.customer_name == company_name)
            .filter(BoletoAReceber.description == auto_description)
            .order_by(BoletoAReceber.id.desc())
            .first()
        )

        if existing:
            existing.customer_email = email or existing.customer_email
            existing.due_date = resolved_due_date
            existing.amount = amount
            if (existing.status or "").upper().strip() != "PAGO":
                existing.status = "A_VENCER"
                existing.paid_at = None
            updated += 1
            continue

        db.add(
            BoletoAReceber(
                competence_month=competence,
                customer_name=company_name,
                customer_email=email,
                description=auto_description,
                due_date=resolved_due_date,
                amount=amount,
                status="A_VENCER",
            )
        )
        created += 1

    db.commit()

    return toast_redirect(
        with_query_params(
            _divisao_custos_url(competence),
            gerar_boletos="ok",
            created=created,
            updated=updated,
            skipped=skipped,
        ),
    )


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
    competence = clamp_competence(competence) or competence
    # Cadastro manual (mantém para novas construtoras)
    name_value = (name or "").strip()
    if not name_value:
        return toast_redirect(
            _divisao_custos_url(competence),
            kind="err",
            message="Informe o nome da construtora.",
        )

    area_val, area_error = _parse_optional_number(area_m2, field_label="área (m²)")
    if area_error:
        return toast_redirect(_divisao_custos_url(competence), kind="err", message=area_error)
    # Aceita 0,12 / 0.12 / 12 / 12% (salva sempre como FRAÇÃO)
    pct_val, pct_error = _parse_percentual_input(percentual)
    if pct_error:
        return toast_redirect(_divisao_custos_url(competence), kind="err", message=pct_error)

    c = RateioCompany(
        name=name_value,
        legal_name=(legal_name.strip() or None),
        cnpj=(cnpj.strip() or None),
        area_m2=area_val,
        percentual=pct_val,
        notes=(notes.strip() or None),
        active=True,
    )
    db.add(c)
    db.commit()
    return toast_redirect(_divisao_custos_url(competence))


@router.post("/divisao-custos/construtoras/{company_id}/update")
def construtoras_update(
    company_id: int,
    competence: str = Form(...),
    name: str = Form(""),
    legal_name: str = Form(""),
    cnpj: str = Form(""),
    area_m2: str = Form(""),
    percentual: str = Form(""),
    notes: str = Form(""),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    """Permite editar o percentual (e opcionalmente dados básicos) de uma construtora."""

    competence = clamp_competence(competence) or competence
    c = db.query(RateioCompany).get(company_id)
    if not c:
        return toast_redirect(
            _divisao_custos_url(competence),
            kind="err",
            message="Construtora não encontrada.",
        )

    # Atualiza campos opcionais (se vierem preenchidos)
    name_value = (name or "").strip()
    if not name_value:
        return toast_redirect(
            _divisao_custos_url(competence),
            kind="err",
            message="Informe o nome da construtora.",
        )

    area_val, area_error = _parse_optional_number(area_m2, field_label="área (m²)")
    if area_error:
        return toast_redirect(_divisao_custos_url(competence), kind="err", message=area_error)

    c.name = name_value
    c.legal_name = (legal_name or "").strip() or None
    c.cnpj = (cnpj or "").strip() or None
    c.area_m2 = area_val
    c.notes = (notes or "").strip() or None

    # Percentual: aceita 0,12 / 0.12 / 12 / 12% (salva sempre como FRAÇÃO)
    pct_val, pct_error = _parse_percentual_input(percentual)
    if pct_error:
        return toast_redirect(_divisao_custos_url(competence), kind="err", message=pct_error)
    c.percentual = pct_val

    db.commit()
    return toast_redirect(_divisao_custos_url(competence))


@router.post("/divisao-custos/construtoras/{company_id}/delete")
def construtoras_delete(
    company_id: int,
    competence: str = Form(...),
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    competence = clamp_competence(competence) or competence
    c = db.query(RateioCompany).get(company_id)
    if c:
        db.delete(c)
        db.commit()
        return toast_redirect(_divisao_custos_url(competence))
    return toast_redirect(
        _divisao_custos_url(competence),
        kind="err",
        message="Construtora não encontrada.",
    )


@router.get("/divisao-custos/pdf/{company_id}")
def company_pdf(
    company_id: int,
    competence: str,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    """Gera o PDF individual (demonstração de custos) de uma construtora."""

    import io

    competence = clamp_competence(competence) or competence
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




@router.get("/divisao-custos/pdf/resumo")
def rateio_summary_pdf(
    competence: str,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    """PDF resumo do rateio do mês (quanto cada construtora deve pagar)."""
    competence = clamp_competence(competence) or competence
    data = compute_divisao_custos(db, competence)
    pdf_bytes = generate_rateio_summary_pdf_bytes(data)
    filename = f"rateio_resumo_{competence}.pdf"
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

    competence = clamp_competence(competence) or competence
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
