from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader


INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#64748B")
LINE = colors.HexColor("#E5E7EB")
BRAND_GREEN = colors.HexColor("#08843B")

_LOGO_READER = None
_LOGO_PATH = Path(__file__).resolve().parents[1] / "static" / "branding" / "arcvsctudo.png"


def _logo_reader():
    global _LOGO_READER
    if _LOGO_READER is None and _LOGO_PATH.exists():
        _LOGO_READER = ImageReader(str(_LOGO_PATH))
    return _LOGO_READER


def draw_logo(canv, *, x: float, y: float, max_w: float = 68 * mm, max_h: float = 20 * mm) -> bool:
    logo = _logo_reader()
    if not logo:
        return False
    iw, ih = logo.getSize()
    scale = min(max_w / iw, max_h / ih)
    w = iw * scale
    h = ih * scale
    canv.drawImage(logo, x + (max_w - w), y + (max_h - h) / 2, width=w, height=h, preserveAspectRatio=True, mask="auto")
    return True


def header_footer_factory(title: str, subtitle: str = "", footer_text: str = "Desenvolvido EasyTech - Facilitando a tecnologia"):
    page_w, page_h = A4

    def _draw(canv, doc):
        canv.saveState()

        x0 = doc.leftMargin
        y_top = page_h - doc.topMargin + 8 * mm

        canv.setFillColor(INK)
        canv.setFont("Helvetica-Bold", 12)
        canv.drawString(x0, y_top, title)

        if subtitle:
            canv.setFillColor(MUTED)
            canv.setFont("Helvetica", 9)
            canv.drawString(x0, y_top - 12, subtitle)

        draw_logo(
            canv,
            x=page_w - doc.rightMargin - 68 * mm,
            y=y_top - 9.5 * mm,
            max_w=68 * mm,
            max_h=20 * mm,
        )

        canv.setStrokeColor(LINE)
        canv.setLineWidth(0.8)
        canv.line(x0, y_top - 18, page_w - doc.rightMargin, y_top - 18)

        canv.line(doc.leftMargin, doc.bottomMargin - 6, page_w - doc.rightMargin, doc.bottomMargin - 6)
        canv.setFillColor(MUTED)
        canv.setFont("Helvetica", 8.2)
        canv.drawString(doc.leftMargin, doc.bottomMargin - 18, f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        canv.drawCentredString(page_w / 2, doc.bottomMargin - 18, footer_text)
        canv.drawRightString(page_w - doc.rightMargin, doc.bottomMargin - 18, f"Pagina {canv.getPageNumber()}")
        canv.restoreState()

    return _draw
