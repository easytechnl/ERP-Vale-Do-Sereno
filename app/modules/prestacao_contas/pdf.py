from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT

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


def boletos_previstos_pdf_bytes(competence, boletos_pagar: dict | None = None, boletos_pagar_next: dict | None = None) -> bytes:
    """PDF: boletos previstos para pagamento (pendentes do mês + próximos)."""
    if isinstance(competence, dict) and boletos_pagar is None:
        payload = competence
        competence = str(payload.get("competence") or "")
        boletos_pagar = payload.get("boletos_pagar") or {}
        boletos_pagar_next = payload.get("boletos_pagar_next") or {}
    boletos_pagar = boletos_pagar or {}
    boletos_pagar_next = boletos_pagar_next or {}

    nxt = str(boletos_pagar_next.get("competence") or "")
    previstos_cur = list(boletos_pagar.get("previstos") or [])
    previstos_nxt = list(boletos_pagar_next.get("previstos") or [])

    buf, doc, st = _mk_doc()
    story = []
    title = "Prestação de Contas — Boletos Previstos"
    subtitle = f"Competência base: {competence}"
    story.append(Paragraph(title, st["h1"]))
    story.append(Paragraph(f"Competência base: <b>{competence}</b>", st["normal"]))
    if nxt:
        story.append(Paragraph(f"Próxima competência: <b>{nxt}</b>", st["normal"]))
    story.append(Paragraph(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", st["small"]))
    story.append(Spacer(1, 10))

    def _table(title: str, items: list[dict]):
        story.append(Paragraph(title, st["h2"]))
        if not items:
            story.append(Paragraph("Nenhum boleto nesta seção.", st["small"]))
            story.append(Spacer(1, 8))
            return
        rows = [["Beneficiário", "Descrição", "Vencimento", "Valor", "NF"]]
        for b in items:
            due = b.get("due_date")
            due_s = due.strftime("%d/%m/%Y") if hasattr(due, "strftime") and due else "—"
            nf = b.get("nota_fiscal")
            nf_s = "—"
            if isinstance(nf, dict):
                nf_s = f"{nf.get('numero') or ''}".strip() or "—"
            rows.append([
                b.get("beneficiario") or "—",
                (b.get("descricao") or "—")[:60],
                due_s,
                f"R${NBSP}{_brl(float(b.get('amount') or 0.0))}",
                nf_s,
            ])
        tbl = Table(rows, colWidths=[52 * mm, 48 * mm, 22 * mm, 28 * mm, 20 * mm])
        tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 9),
                    ("FONTSIZE", (0, 1), (-1, -1), 9),
                    ("BOX", (0, 0), (-1, -1), 1, BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_SOFT]),
                    ("ALIGN", (2, 1), (2, -1), "CENTER"),
                    ("ALIGN", (3, 1), (3, -1), "RIGHT"),
                ]
            )
        )
        story.append(tbl)
        story.append(Spacer(1, 10))

    _table(f"Pendentes / Vencidos — {competence}", previstos_cur)
    if nxt:
        _table(f"Previstos — {nxt}", previstos_nxt)

    story.append(Paragraph("Desenvolvido EasyTech — Facilitando a tecnologia", st["small"]))
    on_page = header_footer_factory(title=title, subtitle=subtitle)
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


def boletos_status_pdf_bytes(competence, boletos_pagar: dict | None = None) -> bytes:
    """PDF: boletos pagos e boletos vencidos (competência)."""
    if isinstance(competence, dict) and boletos_pagar is None:
        payload = competence
        competence = str(payload.get("competence") or "")
        boletos_pagar = payload.get("boletos_pagar") or {}
    boletos_pagar = boletos_pagar or {}

    pagos = list(boletos_pagar.get("pagos") or [])
    vencidos = list(boletos_pagar.get("vencidos") or [])

    buf, doc, st = _mk_doc()
    story = []
    title = "Prestação de Contas — Boletos (Pagos e Vencidos)"
    subtitle = f"Competência: {competence}"
    story.append(Paragraph(title, st["h1"]))
    story.append(Paragraph(f"Competência: <b>{competence}</b>", st["normal"]))
    story.append(Paragraph(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", st["small"]))
    story.append(Spacer(1, 10))

    def _simple(title: str, items: list[dict]):
        story.append(Paragraph(title, st["h2"]))
        if not items:
            story.append(Paragraph("Nenhum registro.", st["small"]))
            story.append(Spacer(1, 8))
            return
        rows = [["Beneficiário", "Vencimento", "Valor"]]
        total = 0.0
        for b in items:
            due = b.get("due_date")
            due_s = due.strftime("%d/%m/%Y") if hasattr(due, "strftime") and due else "—"
            amt = float(b.get("amount") or 0.0)
            total += amt
            rows.append([b.get("beneficiario") or "—", due_s, f"R${NBSP}{_brl(amt)}"])
        rows.append(["", "Total", f"R${NBSP}{_brl(total)}"])
        tbl = Table(rows, colWidths=[92 * mm, 30 * mm, 40 * mm])
        tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("BOX", (0, 0), (-1, -1), 1, BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, BG_SOFT]),
                    ("ALIGN", (1, 1), (1, -1), "CENTER"),
                    ("ALIGN", (2, 1), (2, -1), "RIGHT"),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ("TEXTCOLOR", (0, -1), (-1, -1), BRAND_GREEN),
                ]
            )
        )
        story.append(tbl)
        story.append(Spacer(1, 12))

    _simple("Boletos pagos", pagos)
    _simple("Boletos vencidos", vencidos)
    story.append(Paragraph("Desenvolvido EasyTech — Facilitando a tecnologia", st["small"]))
    on_page = header_footer_factory(title=title, subtitle=subtitle)
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


def prestacao_resumo_pdf_bytes(competence, current: dict | None = None, previous: dict | None = None, saldo_var_pct=None, boletos_pagar_next: dict | None = None) -> bytes:
    """PDF: resumo do mês + variação vs mês anterior + próximos boletos."""
    if isinstance(competence, dict) and current is None:
        payload = competence
        competence = str(payload.get("competence") or "")
        current = payload.get("current") or {}
        previous = payload.get("previous") or {}
        saldo_var_pct = payload.get("saldo_var_pct")
        boletos_pagar_next = payload.get("boletos_pagar_next") or {}
    current = current or {}
    previous = previous or {}
    boletos_pagar_next = boletos_pagar_next or {}

    nxt = str(boletos_pagar_next.get("competence") or "")

    buf, doc, st = _mk_doc()
    story = []
    title = "Prestação de Contas — Resumo"
    subtitle = f"Competência: {competence}"
    story.append(Paragraph(title, st["h1"]))
    story.append(Paragraph(f"Competência: <b>{competence}</b>", st["normal"]))
    story.append(Paragraph(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", st["small"]))
    story.append(Spacer(1, 10))

    var_pct_txt = "—" if saldo_var_pct is None else f"{float(saldo_var_pct):.2f}%"
    tbl = Table(
        [
            ["Entradas", f"R${NBSP}{_brl(float(current.get('entradas') or 0.0))}", f"R${NBSP}{_brl(float(previous.get('entradas') or 0.0))}"],
            ["Saídas", f"R${NBSP}{_brl(float(current.get('saidas') or 0.0))}", f"R${NBSP}{_brl(float(previous.get('saidas') or 0.0))}"],
            ["Saldo final (com ajuste)", f"R${NBSP}{_brl(float(current.get('saldo') or 0.0))}", f"R${NBSP}{_brl(float(previous.get('saldo') or 0.0))}"],
            ["Variação do saldo", var_pct_txt, ""],
        ],
        colWidths=[60 * mm, 50 * mm, 50 * mm],
    )
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("BOX", (0, 0), (-1, -1), 1, BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_SOFT]),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("TEXTCOLOR", (0, 2), (-1, 2), BRAND_GREEN),
                ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
            ]
        )
    )
    story.append(Paragraph(f"Comparativo: {previous.get('competence') or ''} x {current.get('competence') or ''}", st["h2"]))
    story.append(tbl)
    story.append(Spacer(1, 12))

    if nxt:
        story.append(Paragraph(f"Boletos previstos — {nxt}", st["h2"]))
        total_prev = float(boletos_pagar_next.get("pending_total") or 0.0)
        story.append(Paragraph(f"Total previsto: <b>R${NBSP}{_brl(total_prev)}</b>", st["normal"]))
        story.append(Spacer(1, 6))

        rows = [["Beneficiário", "Vencimento", "Valor"]]
        for b in (boletos_pagar_next.get("previstos") or [])[:35]:
            due = b.get("due_date")
            due_s = due.strftime("%d/%m/%Y") if hasattr(due, "strftime") and due else "—"
            rows.append([b.get("beneficiario") or "—", due_s, f"R${NBSP}{_brl(float(b.get('amount') or 0.0))}"])
        tbl2 = Table(rows, colWidths=[92 * mm, 30 * mm, 40 * mm])
        tbl2.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("BOX", (0, 0), (-1, -1), 1, BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_SOFT]),
                    ("ALIGN", (1, 1), (1, -1), "CENTER"),
                    ("ALIGN", (2, 1), (2, -1), "RIGHT"),
                ]
            )
        )
        story.append(tbl2)
        story.append(Spacer(1, 12))

    story.append(Paragraph("Desenvolvido EasyTech — Facilitando a tecnologia", st["small"]))
    on_page = header_footer_factory(title=title, subtitle=subtitle)
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()
