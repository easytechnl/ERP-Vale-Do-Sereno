from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT

from app.core.pdf_branding import header_footer_factory


BRAND_GREEN = colors.HexColor("#08843b")
BRAND_DARK = colors.HexColor("#0B1220")
MUTED = colors.HexColor("#64748b")
BORDER = colors.HexColor("#e5e7eb")
BG_SOFT = colors.HexColor("#f8fafc")

NBSP = "\u00A0"


def _brl(value: float) -> str:
    s = f"{float(value):,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def generate_rateio_summary_pdf_bytes(data: dict) -> bytes:
    """Gera um PDF resumido com quanto cada construtora deve pagar na competência."""

    competence = str(data.get("competence") or "")
    reserve_rate = float(data.get("reserve_rate") or 0.05)
    companies = data.get("companies") or []
    total_despesas = float(data.get("total_despesas") or 0.0)
    total_reserva = float(data.get("total_reserva") or 0.0)
    total_final = float(data.get("total_com_reserva") or 0.0)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=26 * mm,
        bottomMargin=16 * mm,
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=14, textColor=BRAND_DARK, spaceAfter=6)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9, textColor=MUTED)
    normal = ParagraphStyle("normal", parent=styles["Normal"], fontSize=10, textColor=BRAND_DARK)
    normal_right = ParagraphStyle("normal_right", parent=normal, alignment=TA_RIGHT)

    story = []
    title = "Divisão de Custos — Resumo"
    subtitle = f"Competência: {competence}" if competence else "Resumo consolidado"
    story.append(Paragraph(title, h1))
    story.append(Paragraph(f"Competência: <b>{competence}</b>", normal))
    story.append(Paragraph(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", small))
    story.append(Spacer(1, 10))

    # Totais
    totals_tbl = Table(
        [
            ["Total de despesas", f"R${NBSP}{_brl(total_despesas)}"],
            [f"Fundo de reserva ({int(reserve_rate * 100)}%)", f"R${NBSP}{_brl(total_reserva)}"],
            ["Total a arrecadar", f"R${NBSP}{_brl(total_final)}"],
        ],
        colWidths=[90 * mm, 70 * mm],
    )
    totals_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BG_SOFT),
                ("BOX", (0, 0), (-1, -1), 1, BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("TEXTCOLOR", (0, 0), (-1, -1), BRAND_DARK),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 2), (-1, 2), BRAND_GREEN),
            ]
        )
    )
    story.append(totals_tbl)
    story.append(Spacer(1, 12))

    # Tabela por construtora
    header = [
        "Construtora",
        "%",
        "Base",
        "Reserva",
        "Total",
    ]
    rows = [header]
    for c in companies:
        pct = float(c.get("percentual") or 0.0)
        rows.append(
            [
                c.get("name") or "",
                f"{pct * 100:.4f}%",
                f"R${NBSP}{_brl(float(c.get('valor_base') or 0.0))}",
                f"R${NBSP}{_brl(float(c.get('reserva') or 0.0))}",
                f"R${NBSP}{_brl(float(c.get('total') or 0.0))}",
            ]
        )

    tbl = Table(rows, colWidths=[60 * mm, 20 * mm, 30 * mm, 30 * mm, 30 * mm])
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("BOX", (0, 0), (-1, -1), 1, BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_SOFT]),
            ]
        )
    )

    story.append(Paragraph("Resumo por construtora", ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, textColor=BRAND_DARK, spaceAfter=6)))
    story.append(tbl)
    story.append(Spacer(1, 12))
    story.append(Paragraph('Desenvolvido EasyTech — Facilitando a tecnologia', small))

    on_page = header_footer_factory(title=title, subtitle=subtitle)
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()
