from __future__ import annotations

import datetime as dt
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy.orm import Session

from app.models.boletos_receber import BoletoAReceber
from app.modules.rateio.service import list_expenses_for_competence


FIVE_PERCENT_RATE = Decimal("0.05")


REPORT_ORDER = ("paid", "paid_5_percent", "due_soon", "overdue", "investment", "all")

REPORT_META: dict[str, dict[str, str]] = {
    "paid": {
        "title": "Boletos pagos",
        "description": "Somente boletos pagos. Este arquivo sai sem o nome da construtora.",
        "filename_base": "boletos_pagos_sem_construtora",
        "footnote": "Arquivo sem a coluna de cliente/construtora.",
    },
    "paid_5_percent": {
        "title": "5% dos boletos pagos",
        "description": "Apura 5% sobre o valor de todos os boletos pagos na competencia. Este arquivo sai sem o nome da construtora.",
        "filename_base": "cinco_por_cento_boletos_pagos",
        "footnote": "Arquivo sem a coluna de cliente/construtora e com o calculo de 5% sobre cada valor pago.",
    },
    "due_soon": {
        "title": "Boletos a vencer",
        "description": "Boletos em aberto com vencimento futuro ou ainda nao vencidos.",
        "filename_base": "boletos_a_vencer",
        "footnote": "Considera todos os boletos em aberto que ainda nao estao vencidos.",
    },
    "overdue": {
        "title": "Boletos vencidos",
        "description": "Boletos em aberto ja vencidos na competencia selecionada.",
        "filename_base": "boletos_vencidos",
        "footnote": "Usa a data de vencimento e o status atual do boleto.",
    },
    "investment": {
        "title": "Boletos pagos + despesas do rateio",
        "description": "Consolidado de todas as despesas adicionadas na divisao de custos e todos os boletos pagos, mostrando somente data e valor.",
        "filename_base": "boletos_pagos_despesas_rateio",
        "footnote": "Relatorio simplificado com somente data e valor.",
    },
    "all": {
        "title": "Todos os boletos",
        "description": "Lista consolidada com pagos, a vencer e vencidos.",
        "filename_base": "boletos_todos",
        "footnote": "Visao completa da competencia selecionada.",
    },
}


def _money(value: Any) -> float:
    return float(Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _percent_amount(value: Any, rate: Decimal = FIVE_PERCENT_RATE) -> float:
    return _money(Decimal(str(value or 0)) * rate)


def _brl(value: Any) -> str:
    amount = _money(value)
    text = f"{amount:,.2f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _format_date(value: dt.date | dt.datetime | None) -> str:
    if value is None:
        return "-"
    if isinstance(value, dt.datetime):
        value = value.date()
    return value.strftime("%d/%m/%Y")


def _clean_text(value: Any, fallback: str = "-") -> str:
    text = str(value or "").strip()
    return text or fallback


def _as_date(value: dt.date | dt.datetime | None) -> dt.date | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    return value


def _parse_br_date(value: str | None) -> dt.date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return dt.datetime.strptime(raw, "%d/%m/%Y").date()
    except Exception:
        return None


def _is_paid_status(status: str | None) -> bool:
    normalized = (status or "").upper().strip()
    return ("PAG" in normalized) or ("BAIX" in normalized)


def _sort_due(item: dict[str, Any]) -> tuple[dt.date, str, int]:
    due = item.get("due_date") or dt.date.max
    return (due, str(item.get("customer_name") or "").lower(), int(item.get("id") or 0))


def _sort_paid(item: dict[str, Any]) -> tuple[dt.date, dt.date, str, int]:
    paid_at = item.get("paid_at_date") or dt.date.min
    due = item.get("due_date") or dt.date.min
    return (paid_at, due, str(item.get("description") or "").lower(), int(item.get("id") or 0))


def _sort_all(item: dict[str, Any]) -> tuple[dt.date, str, int]:
    due = item.get("due_date") or dt.date.max
    return (due, str(item.get("status_label") or ""), int(item.get("id") or 0))


def _collect_items(db: Session, competence: str) -> list[dict[str, Any]]:
    today = dt.date.today()
    rows = (
        db.query(BoletoAReceber)
        .filter(BoletoAReceber.competence_month == competence)
        .order_by(BoletoAReceber.id.desc())
        .all()
    )

    items: list[dict[str, Any]] = []
    for row in rows:
        raw_status = (row.status or "A_VENCER").upper().strip()
        amount = _money(row.amount)
        fee_5_percent = _percent_amount(amount)
        paid_at_date = _as_date(getattr(row, "paid_at", None))
        is_paid = _is_paid_status(raw_status)
        is_overdue = bool(
            (not is_paid)
            and (
                raw_status == "VENCIDO"
                or (row.due_date is not None and row.due_date < today)
            )
        )
        is_open = bool((not is_paid) and (not is_overdue))
        items.append(
            {
                "id": row.id,
                "competence_month": competence,
                "customer_name": _clean_text(row.customer_name),
                "customer_email": _clean_text(row.customer_email),
                "description": _clean_text(row.description),
                "due_date": row.due_date,
                "due_date_text": _format_date(row.due_date),
                "paid_at_date": paid_at_date,
                "paid_at_text": _format_date(paid_at_date),
                "amount": amount,
                "amount_text": f"R$ {_brl(amount)}",
                "fee_5_percent": fee_5_percent,
                "fee_5_percent_text": f"R$ {_brl(fee_5_percent)}",
                "status_raw": raw_status,
                "status_label": "PAGO" if is_paid else ("VENCIDO" if is_overdue else "A VENCER"),
                "is_paid": is_paid,
                "is_overdue": is_overdue,
                "is_open": is_open,
            }
        )

    return sorted(items, key=_sort_all)


def _select_items(report_key: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if report_key in {"paid", "paid_5_percent"}:
        return sorted([item for item in items if item["is_paid"]], key=_sort_paid, reverse=True)
    if report_key == "due_soon":
        return sorted([item for item in items if item["is_open"]], key=_sort_due)
    if report_key == "overdue":
        return sorted([item for item in items if item["is_overdue"]], key=_sort_due)
    if report_key == "investment":
        return sorted([item for item in items if item["is_paid"]], key=_sort_paid, reverse=True)
    return list(items)


def _columns_for(report_key: str) -> list[dict[str, Any]]:
    if report_key == "paid":
        return [
            {"key": "competence_month", "label": "Competencia", "width_mm": 22, "align": "center"},
            {"key": "paid_at_text", "label": "Pagamento", "width_mm": 24, "align": "center"},
            {"key": "due_date_text", "label": "Vencimento", "width_mm": 24, "align": "center"},
            {"key": "description", "label": "Descricao", "width_mm": 72, "align": "left"},
            {"key": "status_label", "label": "Status", "width_mm": 18, "align": "center"},
            {"key": "amount_text", "label": "Valor pago", "width_mm": 22, "align": "right"},
        ]
    if report_key == "paid_5_percent":
        return [
            {"key": "competence_month", "label": "Competencia", "width_mm": 20, "align": "center"},
            {"key": "paid_at_text", "label": "Pagamento", "width_mm": 24, "align": "center"},
            {"key": "due_date_text", "label": "Vencimento", "width_mm": 24, "align": "center"},
            {"key": "description", "label": "Descricao", "width_mm": 59, "align": "left"},
            {"key": "amount_text", "label": "Valor pago", "width_mm": 27, "align": "right"},
            {"key": "fee_5_percent_text", "label": "Valor 5%", "width_mm": 28, "align": "right"},
        ]
    if report_key == "investment":
        return [
            {"key": "data", "label": "Data", "width_mm": 55, "align": "center"},
            {"key": "valor", "label": "Valor", "width_mm": 55, "align": "right"},
        ]
    if report_key == "all":
        return [
            {"key": "competence_month", "label": "Competencia", "width_mm": 20, "align": "center"},
            {"key": "customer_name", "label": "Cliente", "width_mm": 34, "align": "left"},
            {"key": "due_date_text", "label": "Vencimento", "width_mm": 22, "align": "center"},
            {"key": "paid_at_text", "label": "Pagamento", "width_mm": 22, "align": "center"},
            {"key": "description", "label": "Descricao", "width_mm": 42, "align": "left"},
            {"key": "status_label", "label": "Status", "width_mm": 18, "align": "center"},
            {"key": "amount_text", "label": "Valor", "width_mm": 24, "align": "right"},
        ]
    return [
        {"key": "competence_month", "label": "Competencia", "width_mm": 22, "align": "center"},
        {"key": "customer_name", "label": "Cliente", "width_mm": 42, "align": "left"},
        {"key": "due_date_text", "label": "Vencimento", "width_mm": 24, "align": "center"},
        {"key": "description", "label": "Descricao", "width_mm": 54, "align": "left"},
        {"key": "status_label", "label": "Status", "width_mm": 18, "align": "center"},
        {"key": "amount_text", "label": "Valor", "width_mm": 22, "align": "right"},
    ]


def _summary_lines(report_key: str, items: list[dict[str, Any]]) -> list[tuple[str, str]]:
    amount_total = _money(sum(item["amount"] for item in items))
    if report_key == "paid_5_percent":
        fee_total = _money(sum(item["fee_5_percent"] for item in items))
        return [
            ("Quantidade de boletos pagos", str(len(items))),
            ("Total dos boletos pagos", f"R$ {_brl(amount_total)}"),
            ("Total de 5%", f"R$ {_brl(fee_total)}"),
        ]
    return [
        ("Quantidade de boletos", str(len(items))),
        ("Total do relatorio", f"R$ {_brl(amount_total)}"),
    ]


def _card_metrics(report_key: str, items: list[dict[str, Any]]) -> list[dict[str, str]]:
    amount_total = _money(sum(item["amount"] for item in items))
    if report_key == "paid_5_percent":
        fee_total = _money(sum(item["fee_5_percent"] for item in items))
        return [
            {"label": "Boletos pagos", "value": str(len(items))},
            {"label": "Total pago", "value": f"R$ {_brl(amount_total)}"},
            {"label": "Total 5%", "value": f"R$ {_brl(fee_total)}"},
        ]
    return [
        {"label": "Quantidade", "value": str(len(items))},
        {"label": "Total", "value": f"R$ {_brl(amount_total)}"},
    ]


def _row_value(item: dict[str, Any], key: str) -> str:
    value = item.get(key)
    if value is None:
        return "-"
    text = str(value).strip()
    return text or "-"


def _rateio_expense_rows(db: Session, competence: str) -> tuple[list[dict[str, Any]], float]:
    rows: list[dict[str, Any]] = []
    total = 0.0
    for expense in list_expenses_for_competence(db, competence):
        amount = _money(expense.get("amount"))
        total += amount
        date_text = _clean_text(expense.get("expense_date"))
        rows.append(
            {
                "data": date_text,
                "valor": f"R$ {_brl(amount)}",
                "_sort_date": _parse_br_date(date_text) or dt.date.min,
            }
        )

    return rows, _money(total)


def _build_investment_report(db: Session, competence: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    meta = REPORT_META["investment"]
    paid_items = _select_items("investment", items)

    paid_rows: list[dict[str, Any]] = []
    for item in paid_items:
        paid_rows.append(
            {
                "data": item.get("paid_at_text") or item.get("due_date_text") or "-",
                "valor": item.get("amount_text") or "-",
                "_sort_date": item.get("paid_at_date") or item.get("due_date") or dt.date.min,
            }
        )

    rateio_rows, rateio_total = _rateio_expense_rows(db, competence)

    combined_rows = paid_rows + rateio_rows
    combined_rows.sort(key=lambda row: (row.get("_sort_date") or dt.date.min, str(row.get("valor") or "")))

    columns = _columns_for("investment")
    csv_rows: list[dict[str, str]] = []
    pdf_rows: list[list[str]] = []
    for row in combined_rows:
        csv_row: dict[str, str] = {}
        pdf_row: list[str] = []
        for column in columns:
            value = _row_value(row, str(column["key"]))
            csv_row[str(column["label"])] = value
            pdf_row.append(value)
        csv_rows.append(csv_row)
        pdf_rows.append(pdf_row)

    paid_total = _money(sum(item["amount"] for item in paid_items))
    combined_total = _money(paid_total + rateio_total)

    return {
        "key": "investment",
        "competence": competence,
        "title": meta["title"],
        "description": meta["description"],
        "footnote": meta["footnote"],
        "filename_base": f"{meta['filename_base']}_{competence}",
        "card_metrics": [
            {"label": "Boletos pagos", "value": str(len(paid_items))},
            {"label": "Despesas do rateio", "value": str(len(rateio_rows))},
            {"label": "Total consolidado", "value": f"R$ {_brl(combined_total)}"},
        ],
        "summary_lines": [
            ("Registros no relatorio", str(len(combined_rows))),
            ("Boletos pagos", str(len(paid_items))),
            ("Despesas do rateio", str(len(rateio_rows))),
            ("Total de boletos pagos", f"R$ {_brl(paid_total)}"),
            ("Despesas divisao de custos", f"R$ {_brl(rateio_total)}"),
            ("Total consolidado", f"R$ {_brl(combined_total)}"),
        ],
        "csv_rows": csv_rows,
        "pdf_columns": columns,
        "pdf_rows": pdf_rows,
        "empty_message": "Nenhum boleto pago ou despesa encontrada para este consolidado.",
    }


def _build_report_from_items(competence: str, report_key: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    key = report_key if report_key in REPORT_META else "all"
    meta = REPORT_META[key]
    selected_items = _select_items(key, items)
    columns = _columns_for(key)

    csv_rows: list[dict[str, str]] = []
    pdf_rows: list[list[str]] = []
    for item in selected_items:
        csv_row: dict[str, str] = {}
        pdf_row: list[str] = []
        for column in columns:
            value = _row_value(item, str(column["key"]))
            csv_row[str(column["label"])] = value
            pdf_row.append(value)
        csv_rows.append(csv_row)
        pdf_rows.append(pdf_row)

    filename = f"{meta['filename_base']}_{competence}"
    return {
        "key": key,
        "competence": competence,
        "title": meta["title"],
        "description": meta["description"],
        "footnote": meta["footnote"],
        "filename_base": filename,
        "card_metrics": _card_metrics(key, selected_items),
        "summary_lines": _summary_lines(key, selected_items),
        "csv_rows": csv_rows,
        "pdf_columns": columns,
        "pdf_rows": pdf_rows,
        "empty_message": "Nenhum boleto encontrado para este recorte.",
    }


def build_boleto_receber_report(db: Session, competence: str, report_key: str) -> dict[str, Any]:
    items = _collect_items(db, competence)
    if report_key == "investment":
        return _build_investment_report(db, competence, items)
    return _build_report_from_items(competence, report_key, items)


def build_boleto_receber_report_bundle(db: Session, competence: str) -> dict[str, Any]:
    items = _collect_items(db, competence)
    paid_items = [item for item in items if item["is_paid"]]
    open_items = [item for item in items if item["is_open"]]
    overdue_items = [item for item in items if item["is_overdue"]]
    five_percent_total = _money(sum(item["fee_5_percent"] for item in paid_items))
    rateio_total = _money(sum(_money(expense.get("amount")) for expense in list_expenses_for_competence(db, competence)))

    highlights = [
        {"label": "Todos os boletos", "value": str(len(items))},
        {"label": "Recebido no mes", "value": f"R$ {_brl(sum(item['amount'] for item in paid_items))}"},
        {"label": "5% sobre pagos", "value": f"R$ {_brl(five_percent_total)}"},
        {"label": "A vencer", "value": f"R$ {_brl(sum(item['amount'] for item in open_items))}"},
        {"label": "Vencidos", "value": f"R$ {_brl(sum(item['amount'] for item in overdue_items))}"},
        {"label": "Pagos + rateio", "value": f"R$ {_brl(sum(item['amount'] for item in paid_items) + rateio_total)}"},
    ]

    reports: list[dict[str, Any]] = []
    for report_key in REPORT_ORDER:
        if report_key == "investment":
            reports.append(_build_investment_report(db, competence, items))
        else:
            reports.append(_build_report_from_items(competence, report_key, items))

    return {
        "competence": competence,
        "highlights": highlights,
        "reports": reports,
    }
