from __future__ import annotations

import io
from datetime import datetime
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.pdf_branding import header_footer_factory


def _money(value: float) -> str:
    s = f"{float(value or 0.0):,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_date(value) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y")
    return "-"


def _status_label(status: str | None) -> str:
    st = (status or "").upper()
    if st == "PAGA":
        return "Paga"
    if st == "VENCIDA":
        return "Vencida"
    return "A vencer"


def notas_fiscais_pdf_bytes(rows: Iterable) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=26 * mm,
        bottomMargin=14 * mm,
        title="Notas fiscais cadastradas",
        author="ERP Financeiro",
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=14, textColor=colors.HexColor("#0f172a"))
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#64748b"))

    story = []
    title = "Notas Fiscais Cadastradas"
    subtitle = "Exportação completa das notas fiscais"
    story.append(Paragraph(title, h1))
    story.append(Paragraph(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", small))
    story.append(Spacer(1, 8))

    table_rows = [["ID", "Compet.", "NF", "Fornecedor", "Vencimento", "Valor", "Status"]]
    total = 0.0
    count = 0
    for nf in rows:
        amount = float(nf.amount or 0.0)
        total += amount
        count += 1
        table_rows.append(
            [
                str(nf.id),
                nf.competence_month or "-",
                nf.numero or "-",
                (nf.fornecedor or "-")[:26],
                _fmt_date(nf.due_date),
                _money(amount),
                _status_label(nf.status),
            ]
        )

    if count == 0:
        story.append(Paragraph("Nenhuma nota fiscal cadastrada.", small))
    else:
        col_widths = [12 * mm, 20 * mm, 20 * mm, 50 * mm, 22 * mm, 24 * mm, 22 * mm]
        table = Table(table_rows, colWidths=col_widths, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 8),
                    ("FONTSIZE", (0, 1), (-1, -1), 8),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#e5e7eb")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e5e7eb")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                    ("ALIGN", (0, 1), (2, -1), "CENTER"),
                    ("ALIGN", (4, 1), (4, -1), "CENTER"),
                    ("ALIGN", (5, 1), (5, -1), "RIGHT"),
                    ("ALIGN", (6, 1), (6, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"Total de notas: {count} | Soma: {_money(total)}", small))

    on_page = header_footer_factory(title=title, subtitle=subtitle)
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()
