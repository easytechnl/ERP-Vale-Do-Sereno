from __future__ import annotations

import datetime as dt
import io
from typing import Any, Dict, List

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas

# Platypus
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT

from app.core.pdf_branding import draw_logo


BRAND_GREEN = colors.HexColor("#08843b")
BRAND_DARK = colors.HexColor("#0B1220")
MUTED = colors.HexColor("#64748b")   # slate-500
BORDER = colors.HexColor("#e5e7eb")  # gray-200
BG_SOFT = colors.HexColor("#f8fafc")


def brl(value: float) -> str:
    """Formata moeda em padrão pt-BR: 1.234,56"""
    s = f"{float(value):,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def pct(value: float) -> str:
    return f"{float(value) * 100:.6f}%"


def frac(value: float) -> str:
    """Formata fração em padrão pt-BR: 0,0126556"""
    s = f"{float(value):.7f}"
    return s.replace(".", ",")


def generate_company_cost_division_pdf_bytes(
    *,
    association_name: str,
    competence: str,
    total_despesas: float,
    despesas_breakdown: List[Dict[str, Any]],
    company: Dict[str, Any],
    total_company: float,
    footer_brand: str = "Desenvolvido EasyTech — Facilitando a tecnologia",
) -> bytes:
    """Gera um PDF (bytes) do demonstrativo de divisão de custos de UMA construtora.

    despesas_breakdown deve conter (por item):
      - description, category, expense_date, amount
      - company_part_base, company_part_reserva, company_part
    """

    # Moeda sem quebrar "R$"
    def money(v: float) -> str:
        # &#160; = espaço não-quebrável (evita "R$" ir pra linha de cima)
        return f"R$&#160;{brl(v)}"

    buf = io.BytesIO()
    styles = getSampleStyleSheet()

    base = ParagraphStyle(
        "base",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=13,
        textColor=BRAND_DARK,
        splitLongWords=0,
    )
    muted = ParagraphStyle(
        "muted",
        parent=base,
        fontSize=9,
        leading=12,
        textColor=MUTED,
        splitLongWords=0,
    )

    right = ParagraphStyle("right", parent=base, alignment=TA_RIGHT, splitLongWords=0)
    right_muted = ParagraphStyle("right_muted", parent=muted, alignment=TA_RIGHT, splitLongWords=0)

    # Header/footer no canvas
    def _header_footer(canv: canvas.Canvas, doc):
        w, h = A4

        # header bar
        canv.setFillColor(BRAND_DARK)
        canv.rect(0, h - 32 * mm, w, 32 * mm, fill=1, stroke=0)

        canv.setFillColor(colors.white)
        canv.setFont("Helvetica-Bold", 16)
        canv.drawString(18 * mm, h - 18 * mm, "DEMONSTRATIVO • DIVISÃO DE CUSTOS")

        canv.setFont("Helvetica", 10)
        canv.setFillColor(colors.HexColor("#d1d5db"))
        canv.drawString(18 * mm, h - 24.5 * mm, association_name)
        draw_logo(canv, x=w - 86 * mm, y=h - 22 * mm, max_w=68 * mm, max_h=18 * mm)

        # chip competência
        chip_w, chip_h = 56 * mm, 10 * mm
        chip_x, chip_y = w - chip_w - 18 * mm, h - 23.5 * mm
        canv.setFillColor(BRAND_GREEN)
        canv.roundRect(chip_x, chip_y, chip_w, chip_h, 6, fill=1, stroke=0)
        canv.setFillColor(colors.white)
        canv.setFont("Helvetica-Bold", 9)
        canv.drawCentredString(chip_x + chip_w / 2, chip_y + 3.2 * mm, f"Competência: {competence}")

        # footer
        canv.setFillColor(MUTED)
        canv.setFont("Helvetica", 8)
        now = dt.datetime.now().strftime("%d/%m/%Y %H:%M")
        canv.drawString(18 * mm, 12 * mm, f"Gerado em {now}")
        canv.drawRightString(w - 18 * mm, 12 * mm, footer_brand)
        canv.setFillColor(colors.HexColor("#94a3b8"))
        canv.drawRightString(w - 18 * mm, 7.5 * mm, f"Página {doc.page}")

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=40 * mm,
        bottomMargin=18 * mm,
        title=f"Divisão de Custos - {company.get('name') or ''} - {competence}",
        author="EasyTech",
    )

    story: List[Any] = []

    # =========================
    # CARD: Empresa
    # =========================
    p = float(company.get("percentual") or 0.0)

    company_left = [
        Paragraph(f"<b>{(company.get('name') or '').strip()}</b>", base),
        Paragraph((company.get("legal_name") or "").strip(), muted)
        if (company.get("legal_name") or "").strip()
        else Spacer(1, 1),
        Paragraph(f"<b>CNPJ:</b> {company.get('cnpj') or '—'}", base),
    ]
    company_right = [
        Paragraph(f"<b>Percentual (fração):</b> {frac(p)}  <font color='#64748b'>({pct(p)})</font>", right),
        Paragraph("Percentual conforme base (DOCX)", right_muted),
    ]

    card = Table([[company_left, company_right]], colWidths=[doc.width * 0.62, doc.width * 0.38])
    card.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 1, BORDER),
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(card)
    story.append(Spacer(1, 10))

    # =========================
    # Resumo
    # =========================
    reserve_rate = float(company.get("reserva_rate") or 0.05)
    base_company = float(company.get("valor_base") or company.get("base") or 0.0)
    reserva_company = float(company.get("reserva") or (base_company * reserve_rate))
    total_due = float(company.get("total") or total_company or (base_company + reserva_company))

    summary = Table(
        [[
            Paragraph("<font color='#64748b'>Total de despesas</font><br/><b>%s</b>" % money(total_despesas), base),
            Paragraph("<font color='#64748b'>Percentual</font><br/><b>%s</b>" % (f"{frac(p)} ({pct(p)})"), base),
            Paragraph(
                "<font color='#64748b'>Total a pagar (com reserva)</font><br/>"
                "<font color='#08843b'><b>%s</b></font><br/>"
                "<font color='#64748b' size='8'>Base: %s • Reserva (%s): %s</font>" % (
                    money(total_due), money(base_company), pct(reserve_rate), money(reserva_company)
                ),
                base,
            ),
        ]],
        colWidths=[doc.width / 3.0, doc.width / 3.0, doc.width / 3.0],
    )
    summary.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 1, BORDER),
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(summary)
    story.append(Spacer(1, 14))

    story.append(Paragraph("<b>Detalhamento das despesas e parcela da construtora</b>", base))
    story.append(Spacer(1, 6))

    # =========================
    # TABELA
    # =========================
    tbl = ParagraphStyle(
        "tbl",
        parent=base,
        fontName="Helvetica",
        fontSize=9,
        leading=11,
        splitLongWords=0,
    )
    tbl_muted = ParagraphStyle("tbl_muted", parent=tbl, textColor=MUTED, splitLongWords=0)
    tbl_center = ParagraphStyle("tbl_center", parent=tbl, alignment=1, splitLongWords=0)  # CENTER
    tbl_num = ParagraphStyle("tbl_num", parent=tbl, alignment=TA_RIGHT, splitLongWords=0)
    tbl_num_green = ParagraphStyle("tbl_num_green", parent=tbl_num, textColor=BRAND_GREEN, fontName="Helvetica-Bold", splitLongWords=0)

    hdr = ParagraphStyle(
        "hdr",
        parent=tbl,
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=10,
        textColor=MUTED,
        splitLongWords=0,
    )
    hdr_r = ParagraphStyle("hdr_r", parent=hdr, alignment=TA_RIGHT, splitLongWords=0)

    header = [
        Paragraph("Descrição", hdr),
        Paragraph("Categoria", hdr),
        Paragraph("Data", hdr),
        Paragraph("Valor", hdr_r),
        Paragraph("Base", hdr_r),
        Paragraph("Reserva", hdr_r),
        Paragraph("Total", hdr_r),
    ]

    rows = [header]

    total_val = total_base = total_reserva = total_part = 0.0

    for d in despesas_breakdown:
        desc = (d.get("description") or "").strip() or "—"
        cat = (d.get("category") or "").strip() or "—"
        date_s = (d.get("expense_date") or "").strip() or "—"

        val = float(d.get("amount") or 0.0)
        part_base = float(d.get("company_part_base") or 0.0)
        part_reserva = float(d.get("company_part_reserva") or 0.0)
        part = float(d.get("company_part") or (part_base + part_reserva) or 0.0)

        total_val += val
        total_base += part_base
        total_reserva += part_reserva
        total_part += part

        rows.append(
            [
                Paragraph(desc, tbl),
                Paragraph(cat, tbl_muted),
                Paragraph(date_s, tbl_center),
                Paragraph(money(val), tbl_num),
                Paragraph(money(part_base), tbl_num),
                Paragraph(money(part_reserva), tbl_num),
                Paragraph(money(part), tbl_num_green),
            ]
        )

    # Célula de total (label pequeno + valor maior, alinhado e sem cortar)
    def total_cell(label: str, value: float, green: bool = False) -> Paragraph:
        value_color = "#08843b" if green else "#0B1220"
        return Paragraph(
            f"<font size='8' color='#64748b'><b>{label}</b></font><br/>"
            f"<font size='9.5' color='{value_color}'><b>{money(value)}</b></font>",
            tbl_num,
        )

    # Linha total
    rows.append(
        [
            Paragraph("", tbl),
            Paragraph("", tbl),
            Paragraph("", tbl),
            total_cell("Total", total_val),
            total_cell("Base", total_base),
            total_cell("Reserva", total_reserva),
            total_cell("Total", total_part, green=True),
        ]
    )

    # ✅ Larguras (ajustadas para NÃO cortar dígitos à esquerda tipo "R$50.000,00")
    col_widths = [
        doc.width * 0.25,  # descrição
        doc.width * 0.15,  # categoria
        doc.width * 0.11,  # data
        doc.width * 0.14,  # valor   (↑)
        doc.width * 0.11,  # base    (↑)
        doc.width * 0.11,  # reserva (↑)
        doc.width * 0.13,  # total   (↑)
    ]

    table = Table(rows, colWidths=col_widths, repeatRows=1, hAlign="LEFT")

    table.setStyle(
        TableStyle(
            [
                # Header
                ("BACKGROUND", (0, 0), (-1, 0), BG_SOFT),
                ("LINEBELOW", (0, 0), (-1, 0), 1, BORDER),

                # Zebra
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, BG_SOFT]),

                # Grid leve
                ("GRID", (0, 0), (-1, -2), 0.35, BORDER),

                # Total row
                ("LINEABOVE", (0, -1), (-1, -1), 1, BORDER),
                ("BACKGROUND", (0, -1), (-1, -1), colors.white),

                # Alinhamentos
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
                ("ALIGN", (2, 1), (2, -1), "CENTER"),

                # Padding geral
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),

                # ✅ Padding menor nas colunas numéricas (dá largura útil e evita corte)
                ("LEFTPADDING", (3, 0), (6, -1), 3),
                ("RIGHTPADDING", (3, 0), (6, -1), 3),

                # Mais respiro na última linha
                ("TOPPADDING", (0, -1), (-1, -1), 7),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 7),
            ]
        )
    )

    story.append(table)

    # Build final
    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buf.getvalue()
