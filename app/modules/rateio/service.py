from __future__ import annotations

"""Serviços da Divisão de Custos (antigo Rateio).

Regras (conforme solicitado):
- O sistema NÃO depende de upload de planilhas.
- Percentuais das construtoras vêm do arquivo WORD (DOCX) em app/assets/percentual.docx.
  * Ex: 0,12 (ou 0.12) significa 12%.
- Despesas são inseridas manualmente e podem ser recorrentes (1 mês, 2 meses, 1 ano).
- Divisão de custos = percentual * total de despesas da competência.

Notas:
- O módulo ainda chama "rateio" internamente (nomes de pastas/tabelas),
  mas a UI/rotas exibem "Divisão de Custos".
"""

import datetime as _dt
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from docx import Document
from sqlalchemy.orm import Session

from app.models.rateio import RateioCompany, RateioExpense


# =========================
# Fonte de percentuais (DOCX)
# =========================

DEFAULT_PERCENTUAL_DOCX_FILENAME = "percentual.docx"


def get_percentual_docx_path() -> Path:
    """Arquivo base de percentuais (WORD) embutido no projeto."""
    # .../app/modules/rateio/service.py -> parents[2] == app
    app_dir = Path(__file__).resolve().parents[2]
    return app_dir / "assets" / DEFAULT_PERCENTUAL_DOCX_FILENAME


def _norm_str(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _norm_key_name(v: Any) -> str:
    """Normaliza nome para matching (minúsculo, só alfanum)."""
    s = _norm_str(v).lower()
    return "".join(ch for ch in s if ch.isalnum())


_num_re = re.compile(r"(-?\d+[\d\.,]*\d|-?\d+)(\s*%)?", re.UNICODE)


def _parse_percent_value(raw: Any) -> Optional[float]:
    """Converte texto para fração.

    Aceita:
    - 0,0123 / 0.0123
    - 12% / 12,5%
    - 12 / 12,5 (assume porcentagem se > 1)
    """
    s = _norm_str(raw)
    if not s:
        return None

    m = _num_re.search(s.replace(" ", ""))
    if not m:
        return None

    num_s = m.group(1)
    has_pct_symbol = bool(m.group(2))

    # pt-BR: troca vírgula por ponto
    num_s = num_s.replace(".", "") if ("," in num_s and "." in num_s and num_s.find(",") > num_s.find(".")) else num_s
    num_s = num_s.replace(",", ".")

    try:
        v = float(num_s)
    except Exception:
        return None

    if has_pct_symbol:
        return v / 100.0

    # se veio como 12, considera 12%
    if v > 1.0:
        return v / 100.0

    # veio como fração
    return v


def parse_percentual_docx(path: Path) -> Dict[str, Any]:
    """Extrai lista de construtoras e percentuais do DOCX.

    Esperado: tabela com 2 colunas: Nome | Percentual
    """
    if not path.exists():
        raise FileNotFoundError(f"Arquivo de percentuais não encontrado: {path}")

    doc = Document(str(path))
    rows: List[Dict[str, Any]] = []

    # 1) Tabelas (mais comum)
    for t in doc.tables:
        if len(t.columns) < 2:
            continue
        for r in t.rows:
            cells = r.cells
            if len(cells) < 2:
                continue
            name = _norm_str(cells[0].text)
            pct_raw = _norm_str(cells[1].text)
            pct_val = _parse_percent_value(pct_raw)
            if not name:
                continue
            if pct_val is None:
                continue
            rows.append({"name": name, "percentual": float(pct_val)})

    # 2) Parágrafos (quando o DOCX não está em tabela)
    # Ex.: "Admotta 0,0126556"
    line_re = re.compile(r"^(?P<name>.+?)\s+(?P<val>-?\d+[\d\.,]*\d|-?\d+)(?:\s*%\s*)?$", re.UNICODE)
    for p in doc.paragraphs:
        txt = _norm_str(p.text)
        if not txt:
            continue
        for line in txt.splitlines():
            line = _norm_str(line)
            if not line:
                continue
            m = line_re.match(line)
            if not m:
                continue
            name = _norm_str(m.group("name"))
            val_raw = _norm_str(m.group("val"))

            # ignora linhas sem nome (ex.: "1,0000000")
            if not name or _norm_key_name(name).isdigit():
                continue

            pct_val = _parse_percent_value(val_raw)
            if pct_val is None:
                continue
            rows.append({"name": name, "percentual": float(pct_val)})

    # remove duplicadas mantendo a última ocorrência
    dedup: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = _norm_key_name(r["name"]) or r["name"].lower()
        dedup[key] = r

    final_rows = list(dedup.values())
    total_pct = float(sum(float(r["percentual"]) for r in final_rows))

    return {"rows": final_rows, "total_pct": total_pct, "count": len(final_rows)}


def ensure_companies_seeded_from_docx(db: Session, docx_path: Path) -> tuple[int, float]:
    """Garante que TODAS as construtoras do DOCX existam no banco.

    - Se não existir, cria.
    - Se existir (match por nome normalizado), NÃO sobrescreve percentual (para permitir edição manual).

    Retorna: (alteracoes, total_pct)
    """
    extracted = parse_percentual_docx(docx_path)
    rows = extracted.get("rows") or []
    if not rows:
        return (0, float(extracted.get("total_pct", 0.0) or 0.0))

    existing = db.query(RateioCompany).all()
    by_name: Dict[str, RateioCompany] = {}
    for c in existing:
        nk = _norm_key_name(c.name)
        if nk:
            by_name[nk] = c

    inserted = 0
    updated = 0

    for r in rows:
        nk = _norm_key_name(r.get("name"))
        if not nk:
            continue
        pct = float(r.get("percentual") or 0.0)

        target = by_name.get(nk)
        if target is None:
            db.add(
                RateioCompany(
                    name=_norm_str(r.get("name")),
                    legal_name=None,
                    cnpj=None,
                    area_m2=None,
                    percentual=pct,
                    notes="Base automática (DOCX)",
                    active=True,
                )
            )
            inserted += 1
        else:
            # Importante: não sobrescrevemos o percentual automaticamente para permitir edição manual.
            # Ainda assim, se o percentual estiver "zerado" (caso raro), preenchemos.
            current = float(target.percentual or 0.0)
            if current <= 0 and pct > 0:
                target.percentual = pct
                if not (target.notes or "").strip():
                    target.notes = "Base automática (DOCX)"
                updated += 1

    if inserted or updated:
        db.commit()

    total_pct = float(extracted.get("total_pct") or 0.0)
    return (int(inserted + updated), total_pct)


# =========================
# Despesas (manual + recorrência)
# =========================


def _month_start_end(ym: str) -> tuple[_dt.date, _dt.date]:
    y, m = [int(x) for x in ym.split("-")]
    start = _dt.date(y, m, 1)
    if m == 12:
        end = _dt.date(y + 1, 1, 1) - _dt.timedelta(days=1)
    else:
        end = _dt.date(y, m + 1, 1) - _dt.timedelta(days=1)
    return start, end


def _months_diff(a: _dt.date, b: _dt.date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def expense_occurs_in_month(exp: RateioExpense, ym: str) -> bool:
    start, end = _month_start_end(ym)

    if not exp.active:
        return False
    if exp.expense_date > end:
        return False
    if exp.end_date is not None and exp.end_date < start:
        return False

    if exp.recurrence_months in (None, 0):
        return exp.expense_date >= start and exp.expense_date <= end

    base = exp.expense_date
    diff = _months_diff(_dt.date(base.year, base.month, 1), _dt.date(start.year, start.month, 1))
    return diff >= 0 and (diff % int(exp.recurrence_months) == 0)


def list_expenses_for_competence(db: Session, ym: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    expenses = (
        db.query(RateioExpense)
        .filter(RateioExpense.active == True)  # noqa: E712
        .order_by(RateioExpense.expense_date.asc(), RateioExpense.id.asc())
        .all()
    )
    for e in expenses:
        if expense_occurs_in_month(e, ym):
            out.append(
                {
                    "id": e.id,
                    "description": e.description,
                    "category": e.category or "",
                    "amount": float(e.amount),
                    "expense_date": e.expense_date.strftime("%d/%m/%Y"),
                    "recurrence_months": int(e.recurrence_months or 0),
                    "end_date": e.end_date.strftime("%d/%m/%Y") if e.end_date else "",
                    "notes": e.notes or "",
                }
            )
    return out


# =========================
# Cálculo da Divisão de Custos
# =========================


def compute_cost_division(db: Session, competence: str) -> Dict[str, Any]:
    """Calcula a divisão de custos com base nas despesas cadastradas e % do banco."""

    despesas = list_expenses_for_competence(db, competence)
    total_despesas = float(sum(float(d["amount"]) for d in despesas))

    companies = (
        db.query(RateioCompany)
        .filter(RateioCompany.active == True)  # noqa: E712
        .order_by(RateioCompany.name.asc())
        .all()
    )

    out_companies: List[Dict[str, Any]] = []
    reserve_rate = 0.05  # 5% fundo de reserva (aplicado SOBRE o valor de cada construtora)

    for c in companies:
        pct = float(c.percentual or 0.0)
        if pct > 1:
            pct = pct / 100.0

        base_valor = float(total_despesas) * float(pct)
        reserva = float(base_valor) * float(reserve_rate)
        total_com_reserva = float(base_valor) + float(reserva)

        out_companies.append(
            {
                "id": c.id,
                "name": c.name,
                "legal_name": c.legal_name or "",
                "cnpj": c.cnpj or "",
                "area_m2": float(c.area_m2 or 0.0),
                "percentual": float(pct),
                # Compat: diferentes versões da UI usam chaves diferentes
                # base (sem reserva)
                "valor_base": float(base_valor),
                "base": float(base_valor),
                # fundo de reserva (5%)
                "reserva_rate": float(reserve_rate),
                "reserva": float(reserva),
                # total final
                "valor": float(total_com_reserva),
                "total": float(total_com_reserva),
                "valor_a_pagar": float(total_com_reserva),
                "missing_percentual": bool(pct == 0.0),
            }
        )

    total_reserva = float(sum(float(c.get("reserva") or 0.0) for c in out_companies))
    total_com_reserva = float(total_despesas) + total_reserva

    return {
        "competence": competence,
        "total_despesas": float(total_despesas),
        "reserve_rate": float(reserve_rate),
        "total_reserva": float(total_reserva),
        "total_com_reserva": float(total_com_reserva),
        "despesas": despesas,
        "companies": out_companies,
        "companies_count": len(out_companies),
    }


# Alias para compatibilidade com import antigo usado no router
def compute_divisao_custos(db: Session, competence: str) -> Dict[str, Any]:
    return compute_cost_division(db=db, competence=competence)


def compute_company_breakdown(competence_data: Dict[str, Any], company_id: int) -> Dict[str, Any] | None:
    """Retorna a empresa e uma tabela detalhada (cada despesa e a parcela da empresa)."""
    companies = competence_data.get("companies") or []
    company = None
    for c in companies:
        if int(c.get("id") or 0) == int(company_id):
            company = c
            break
    if not company:
        return None

    pct = float(company.get("percentual") or 0.0)
    reserve_rate = float(company.get("reserva_rate") or competence_data.get("reserve_rate") or 0.05)
    despesas = competence_data.get("despesas") or []

    detailed: List[Dict[str, Any]] = []
    for d in despesas:
        amount = float(d.get("amount") or 0.0)
        part_base = amount * pct
        part_reserva = float(part_base) * float(reserve_rate)
        part_total = float(part_base) + float(part_reserva)
        detailed.append(
            {
                "description": d.get("description") or "",
                "category": d.get("category") or "",
                "expense_date": d.get("expense_date") or "",
                "amount": amount,
                "company_part_base": float(part_base),
                "company_part_reserva": float(part_reserva),
                "company_part": float(part_total),
            }
        )

    total_base = float(sum(x["company_part_base"] for x in detailed))
    total_reserva = float(sum(x["company_part_reserva"] for x in detailed))
    total_final = float(sum(x["company_part"] for x in detailed))

    return {
        "company": company,
        "breakdown": detailed,
        "reserve_rate": float(reserve_rate),
        "total_company_base": float(total_base),
        "total_company_reserva": float(total_reserva),
        "total_company": float(total_final),
    }
