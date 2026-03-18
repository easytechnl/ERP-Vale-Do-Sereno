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


def boleto_receber_report_pdf_bytes(report: dict) -> bytes:
    title = str(report.get("title") or "Relatorio de boletos")
    competence = str(report.get("competence") or "")
    subtitle = f"Competencia: {competence}"
    description = str(report.get("description") or "")
    summary_lines = list(report.get("summary_lines") or [])
    columns = list(report.get("pdf_columns") or [])
    rows = list(report.get("pdf_rows") or [])
    empty_message = str(report.get("empty_message") or "Nenhum dado disponivel.")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=26 * mm,
        bottomMargin=14 * mm,
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=14, textColor=BRAND_DARK, spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=11, textColor=BRAND_DARK, spaceAfter=6)
    normal = ParagraphStyle("normal", parent=styles["Normal"], fontSize=10, textColor=BRAND_DARK, leading=13)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9, textColor=MUTED, leading=12)
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8.6, textColor=BRAND_DARK, leading=10.5)
    cell_right = ParagraphStyle("cell_right", parent=cell, alignment=TA_RIGHT)

    story = [
        Paragraph(title, h1),
        Paragraph(f"Competencia: <b>{competence}</b>", normal),
        Paragraph(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", small),
    ]
    if description:
        story.extend([Spacer(1, 6), Paragraph(description, small)])

    if summary_lines:
        summary_table = Table([[label, value] for (label, value) in summary_lines], colWidths=[70 * mm, 90 * mm])
        summary_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), BG_SOFT),
                    ("BOX", (0, 0), (-1, -1), 1, BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
                    ("TEXTCOLOR", (1, 0), (1, -1), BRAND_GREEN),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.extend([Spacer(1, 10), summary_table])

    story.extend([Spacer(1, 12), Paragraph("Detalhamento", h2)])

    if rows and columns:
        table_header = [str(column.get("label") or "") for column in columns]
        table_rows = [table_header]
        for row in rows:
            formatted_row = []
            for index, value in enumerate(row):
                align = str(columns[index].get("align") or "left")
                style = cell_right if align == "right" else cell
                formatted_row.append(Paragraph(str(value or "-"), style))
            table_rows.append(formatted_row)

        table = Table(
            table_rows,
            colWidths=[float(column.get("width_mm") or 20) * mm for column in columns],
            repeatRows=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 9),
                    ("BOX", (0, 0), (-1, -1), 1, BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.45, BORDER),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_SOFT]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(table)
    else:
        story.append(Paragraph(empty_message, small))

    on_page = header_footer_factory(title=title, subtitle=subtitle)
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buffer.getvalue()
