from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from app.core.pdf_branding import draw_logo


def generate_boleto_pdf(
    out_path: Path,
    *,
    sacado: str,
    competencia: str,
    vencimento: str,
    valor: str,
    linha: str,
    nosso_numero: str,
):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(out_path), pagesize=A4)
    w, h = A4

    c.setFillColor(colors.HexColor("#111827"))
    c.rect(0, h - 32 * mm, w, 32 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(16 * mm, h - 17 * mm, "Boleto Cadastrado")
    c.setFont("Helvetica", 9.5)
    c.drawString(16 * mm, h - 23 * mm, "Documento gerado pelo ERP Financeiro")
    draw_logo(c, x=w - 86 * mm, y=h - 22 * mm, max_w=68 * mm, max_h=18 * mm)

    card_x = 16 * mm
    card_y = h - 130 * mm
    card_w = w - (32 * mm)
    card_h = 84 * mm
    c.setFillColor(colors.white)
    c.setStrokeColor(colors.HexColor("#E5E7EB"))
    c.roundRect(card_x, card_y, card_w, card_h, 7, stroke=1, fill=1)

    y = card_y + card_h - 14 * mm
    c.setFillColor(colors.HexColor("#111827"))
    c.setFont("Helvetica-Bold", 11)
    c.drawString(card_x + 8 * mm, y, f"Sacado: {sacado}")
    y -= 8 * mm
    c.setFont("Helvetica", 10)
    c.drawString(card_x + 8 * mm, y, f"Competencia: {competencia}")
    y -= 6 * mm
    c.drawString(card_x + 8 * mm, y, f"Vencimento: {vencimento}")
    y -= 6 * mm
    c.drawString(card_x + 8 * mm, y, f"Nosso numero: {nosso_numero}")
    y -= 8 * mm

    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.HexColor("#08843B"))
    c.drawString(card_x + 8 * mm, y, f"Valor: R$ {valor}")
    y -= 10 * mm

    c.setFillColor(colors.HexColor("#111827"))
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(card_x + 8 * mm, y, "Linha digitavel:")
    y -= 5.5 * mm
    c.setFont("Helvetica", 9.3)
    c.drawString(card_x + 8 * mm, y, linha[:90])

    c.setStrokeColor(colors.HexColor("#E5E7EB"))
    c.line(16 * mm, 20 * mm, w - 16 * mm, 20 * mm)
    c.setFillColor(colors.HexColor("#64748B"))
    c.setFont("Helvetica", 8)
    c.drawString(16 * mm, 14 * mm, "Gerado pelo ERP Financeiro")
    c.drawRightString(w - 16 * mm, 14 * mm, "Desenvolvido EasyTech - Facilitando a tecnologia")

    c.showPage()
    c.save()
