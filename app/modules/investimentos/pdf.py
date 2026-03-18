from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.pdf_branding import header_footer_factory


BRAND_GREEN = colors.HexColor("#08843b")
BRAND_DARK = colors.HexColor("#0B1220")
MUTED = colors.HexColor("#64748b")
BORDER = colors.HexColor("#e5e7eb")
BG_SOFT = colors.HexColor("#f8fafc")
NBSP = "\u00A0"


def _brl(value: float) -> str:
    formatted = f"{float(value):,.2f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def _signed_amount(kind: str, amount: float) -> float:
    value = float(amount or 0.0)
    if kind == "RESGATE":
        return -abs(value)
    if kind in {"APORTE", "RENDIMENTO"}:
        return abs(value)
    return value


def _mk_doc() -> tuple[io.BytesIO, SimpleDocTemplate, dict]:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=26 * mm,
        bottomMargin=14 * mm,
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=14, textColor=BRAND_DARK, spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=11, textColor=BRAND_DARK, spaceAfter=6)
    normal = ParagraphStyle("normal", parent=styles["Normal"], fontSize=10, textColor=BRAND_DARK)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9, textColor=MUTED)
    right = ParagraphStyle("right", parent=normal, alignment=TA_RIGHT)
    return buf, doc, {"h1": h1, "h2": h2, "normal": normal, "small": small, "right": right}


def investments_report_pdf_bytes(payload: dict) -> bytes:
    report = payload.get("report") or {}
    movements = list(payload.get("movements") or [])
    account_name = str(payload.get("account_name") or "Todas as contas")
    accounts_count = int(payload.get("accounts_count") or 0)

    buf, doc, st = _mk_doc()
    story = []

    start = str(report.get("start") or "")
    end = str(report.get("end") or "")
    totals = report.get("totals") or {}
    series = list(report.get("series") or [])

    title = "Relatorio de Investimentos"
    subtitle = f"Periodo: {start} a {end} | Conta: {account_name}"

    story.append(Paragraph(title, st["h1"]))
    story.append(Paragraph(f"Periodo analisado: <b>{start}</b> ate <b>{end}</b>", st["normal"]))
    story.append(Paragraph(f"Conta: <b>{account_name}</b>", st["normal"]))
    story.append(Paragraph(f"Contas consideradas: <b>{accounts_count}</b>", st["normal"]))
    story.append(Paragraph(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", st["small"]))
    story.append(Spacer(1, 10))

    summary_rows = [
        ["Saldo final", f"R${NBSP}{_brl(float(totals.get('saldo') or 0.0))}"],
        ["Aportes", f"R${NBSP}{_brl(float(totals.get('aportes') or 0.0))}"],
        ["Resgates", f"R${NBSP}{_brl(float(totals.get('resgates') or 0.0))}"],
        ["Rendimentos", f"R${NBSP}{_brl(float(totals.get('rendimentos') or 0.0))}"],
        ["Ajustes", f"R${NBSP}{_brl(float(totals.get('ajustes') or 0.0))}"],
    ]
    summary = Table(summary_rows, colWidths=[65 * mm, 45 * mm])
    summary.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BG_SOFT),
                ("BOX", (0, 0), (-1, -1), 1, BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, BG_SOFT]),
                ("TEXTCOLOR", (0, 0), (-1, 0), BRAND_GREEN),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ]
        )
    )
    story.append(summary)
    story.append(Spacer(1, 12))

    story.append(Paragraph("Serie mensal", st["h2"]))
    if series:
        rows = [["Competencia", "Aportes", "Resgates", "Rendimentos", "Ajustes", "Saldo final"]]
        for row in series:
            rows.append(
                [
                    row.get("competence") or "-",
                    f"R${NBSP}{_brl(float(row.get('aportes') or 0.0))}",
                    f"R${NBSP}{_brl(float(row.get('resgates') or 0.0))}",
                    f"R${NBSP}{_brl(float(row.get('rendimentos') or 0.0))}",
                    f"R${NBSP}{_brl(float(row.get('ajustes') or 0.0))}",
                    f"R${NBSP}{_brl(float(row.get('saldo') or 0.0))}",
                ]
            )
        series_table = Table(rows, colWidths=[26 * mm, 28 * mm, 28 * mm, 30 * mm, 26 * mm, 30 * mm])
        series_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("BOX", (0, 0), (-1, -1), 1, BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_SOFT]),
                    ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ]
            )
        )
        story.append(series_table)
    else:
        story.append(Paragraph("Sem dados no periodo selecionado.", st["small"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Movimentos do periodo", st["h2"]))
    if movements:
        rows = [["Data", "Conta", "Tipo", "Descricao", "Valor"]]
        for entry in movements[:40]:
            signed = _signed_amount(str(entry.get("kind") or ""), float(entry.get("amount") or 0.0))
            rows.append(
                [
                    str(entry.get("entry_date") or "-"),
                    str(entry.get("account_name") or "-")[:24],
                    str(entry.get("kind_label") or entry.get("kind") or "-"),
                    str(entry.get("description") or "-")[:40],
                    f"R${NBSP}{_brl(signed)}",
                ]
            )
        movements_table = Table(rows, colWidths=[22 * mm, 38 * mm, 24 * mm, 74 * mm, 24 * mm])
        movements_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.2),
                    ("BOX", (0, 0), (-1, -1), 1, BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_SOFT]),
                    ("ALIGN", (4, 1), (4, -1), "RIGHT"),
                ]
            )
        )
        story.append(movements_table)
        if len(movements) > 40:
            story.append(Spacer(1, 6))
            story.append(Paragraph("O PDF mostra somente os 40 movimentos mais recentes do periodo.", st["small"]))
    else:
        story.append(Paragraph("Sem movimentos para listar.", st["small"]))

    on_page = header_footer_factory(title=title, subtitle=subtitle)
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()
