from __future__ import annotations

from pathlib import Path
from datetime import datetime
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
)
from reportlab.pdfgen import canvas

from app.core.pdf_branding import header_footer_factory


# =========================
# Helpers (layout + format)
# =========================
PAGE_W, PAGE_H = A4
MARGIN_L = 16 * mm
MARGIN_R = 16 * mm
MARGIN_T = 16 * mm
MARGIN_B = 14 * mm

INK = colors.HexColor("#111827")       # cinza bem escuro
MUTED = colors.HexColor("#6B7280")     # cinza médio
LINE = colors.HexColor("#E5E7EB")      # linha
PAPER = colors.white

CARD_BG = colors.HexColor("#F9FAFB")
ZEBRA = colors.HexColor("#F3F4F6")

# “Sinal” discreto para valores
GOOD_BG = colors.HexColor("#ECFDF5")   # verde clarinho
BAD_BG = colors.HexColor("#FEF2F2")    # vermelho clarinho
NEUTRAL_BG = colors.HexColor("#F3F4F6")


def _now_str() -> str:
    # horário local do servidor; se quiser timezone, trate no seu app
    return datetime.now().strftime("%d/%m/%Y %H:%M")


def _as_float(v: Any) -> float:
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _money_br(v: float) -> str:
    # formata 1234.5 -> 1.234,50
    s = f"{v:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def _kind_label(kind: str | None) -> str:
    if not kind:
        return ""
    k = str(kind).upper()
    if "ENT" in k:
        return "Entrada"
    if "SAI" in k:
        return "Saída"
    return str(kind).title()


def _build_styles():
    styles = getSampleStyleSheet()

    styles.add(
        ParagraphStyle(
            name="TitleX",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            textColor=INK,
            alignment=TA_LEFT,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SubX",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=12,
            textColor=MUTED,
            alignment=TA_LEFT,
        )
    )
    styles.add(
        ParagraphStyle(
            name="H2X",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=INK,
            spaceBefore=8,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodyX",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9.2,
            leading=12,
            textColor=INK,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SmallMuted",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=MUTED,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Cell",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8.8,
            leading=11,
            textColor=INK,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CellRight",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8.8,
            leading=11,
            textColor=INK,
            alignment=TA_RIGHT,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CellCenter",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8.8,
            leading=11,
            textColor=INK,
            alignment=TA_CENTER,
        )
    )
    return styles


def _header_footer(title: str, subtitle: str):
    return header_footer_factory(title=title, subtitle=subtitle)


def _kpi_cards(styles, *, entradas: float, saidas: float, saldo: float) -> Table:
    # fundo do saldo “de acordo” com sinal
    saldo_bg = GOOD_BG if saldo >= 0 else BAD_BG

    data = [
        [
            Paragraph("<b>Entradas</b>", styles["SmallMuted"]),
            Paragraph("<b>Saídas</b>", styles["SmallMuted"]),
            Paragraph("<b>Saldo</b>", styles["SmallMuted"]),
        ],
        [
            Paragraph(f"<b>{_money_br(entradas)}</b>", styles["BodyX"]),
            Paragraph(f"<b>{_money_br(saidas)}</b>", styles["BodyX"]),
            Paragraph(f"<b>{_money_br(saldo)}</b>", styles["BodyX"]),
        ],
    ]

    t = Table(
        data,
        colWidths=[(PAGE_W - MARGIN_L - MARGIN_R) / 3] * 3,
        hAlign="LEFT",
    )

    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (2, 0), CARD_BG),
                ("BACKGROUND", (0, 1), (0, 1), PAPER),
                ("BACKGROUND", (1, 1), (1, 1), PAPER),
                ("BACKGROUND", (2, 1), (2, 1), saldo_bg),
                ("BOX", (0, 0), (-1, -1), 0.8, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.6, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return t


def _build_table(styles, header: list[str], rows: list[list[Any]], col_widths: list[float]) -> Table:
    """
    Tabela premium:
    - header fixo em todas as páginas (repeatRows=1)
    - zebra
    - grid leve
    - quebra por página automática
    """
    table_data: list[list[Any]] = [header] + rows

    t = Table(
        table_data,
        colWidths=col_widths,
        repeatRows=1,
        hAlign="LEFT",
    )

    # zebra (linhas de dados)
    zebra_cmds = []
    for i in range(1, len(table_data)):
        if i % 2 == 0:
            zebra_cmds.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))

    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, LINE),
                ("GRID", (0, 0), (-1, -1), 0.35, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
            + zebra_cmds
        )
    )
    return t


# =========================
# PDFs (premium)
# =========================
def generate_demonstrativo_pdf(out_path: Path, *, competence: str, totals: dict, lines: list[dict]):
    """
    Mantém assinatura; melhora layout (cards + tabela).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    styles = _build_styles()
    entradas = _as_float(totals.get("entradas"))
    saidas = _as_float(totals.get("saidas"))
    saldo = _as_float(totals.get("saldo"))

    title = "Demonstrativo Mensal"
    subtitle = f"Competência: {competence} • Resumo financeiro e lançamentos do período"

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=MARGIN_L,
        rightMargin=MARGIN_R,
        topMargin=26 * mm,
        bottomMargin=18 * mm,
        title=title,
        author="ERP Financeiro",
    )

    story = []

    story.append(Spacer(1, 6))
    story.append(_kpi_cards(styles, entradas=entradas, saidas=saidas, saldo=saldo))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Lançamentos (realizado no mês)", styles["H2X"]))

    # tabela
    header = ["Data", "Descrição", "Tipo", "Status", "Valor"]
    rows = []
    for ln in (lines or []):
        dt = str(ln.get("date", "") or "")
        desc = Paragraph(str(ln.get("name", "") or ""), styles["Cell"])
        val = _as_float(ln.get("amount"))
        tipo = "Entrada" if val >= 0 else "Saída"
        status = str(ln.get("status", "") or "")
        rows.append(
            [
                Paragraph(dt, styles["CellCenter"]),
                desc,
                Paragraph(tipo, styles["CellCenter"]),
                Paragraph(status, styles["CellCenter"]),
                Paragraph(_money_br(abs(val)), styles["CellRight"]),
            ]
        )

    usable_w = PAGE_W - MARGIN_L - MARGIN_R
    col_widths = [18 * mm, usable_w - (18 + 30 + 20 + 26) * mm, 30 * mm, 20 * mm, 26 * mm]

    story.append(_build_table(styles, header, rows, col_widths))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Observação: valores positivos representam entradas e negativos representam saídas.", styles["SmallMuted"]))

    doc.build(story, onFirstPage=_header_footer(title, subtitle), onLaterPages=_header_footer(title, subtitle))


def generate_periodo_pdf(out_path: Path, *, data: dict):
    """
    Mantém assinatura; melhora layout (cards + série mensal como tabela).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    styles = _build_styles()
    start = str(data.get("start", "") or "")
    end = str(data.get("end", "") or "")
    months = int(data.get("months", 0) or 0)

    t = data.get("totals") or {}
    entradas = _as_float(t.get("entradas"))
    saidas = _as_float(t.get("saidas"))
    saldo = _as_float(t.get("saldo"))

    title = "Relatórios por período"
    subtitle = f"Período: {start} a {end} • Consolidação: {months} mês(es)"

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=MARGIN_L,
        rightMargin=MARGIN_R,
        topMargin=26 * mm,
        bottomMargin=18 * mm,
        title=title,
        author="ERP Financeiro",
    )

    story = []
    story.append(Spacer(1, 6))

    # bloco “Filtros”
    filtros = Table(
        [[
            Paragraph("<b>Filtros</b>", styles["BodyX"]),
            Paragraph(f"Período: <b>{start}</b> a <b>{end}</b> • Janela: <b>{months}</b> mês(es)", styles["BodyX"]),
        ]],
        colWidths=[22 * mm, (PAGE_W - MARGIN_L - MARGIN_R) - 22 * mm],
        hAlign="LEFT",
    )
    filtros.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CARD_BG),
                ("BOX", (0, 0), (-1, -1), 0.8, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(filtros)
    story.append(Spacer(1, 8))

    story.append(_kpi_cards(styles, entradas=entradas, saidas=saidas, saldo=saldo))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Série mensal", styles["H2X"]))

    header = ["Competência", "Entradas", "Saídas", "Saldo"]
    series = data.get("series") or []
    rows = []
    for row in series:
        comp = str(row.get("competence", "") or "")
        e = _as_float(row.get("entradas"))
        s = _as_float(row.get("saidas"))
        sal = _as_float(row.get("saldo"))
        rows.append(
            [
                Paragraph(comp, styles["CellCenter"]),
                Paragraph(_money_br(e), styles["CellRight"]),
                Paragraph(_money_br(s), styles["CellRight"]),
                Paragraph(_money_br(sal), styles["CellRight"]),
            ]
        )

    usable_w = PAGE_W - MARGIN_L - MARGIN_R
    col_widths = [32 * mm, (usable_w - 32 * mm) / 3, (usable_w - 32 * mm) / 3, (usable_w - 32 * mm) / 3]

    story.append(_build_table(styles, header, rows, col_widths))

    doc.build(story, onFirstPage=_header_footer(title, subtitle), onLaterPages=_header_footer(title, subtitle))


def generate_lancamentos_pdf(
    out_path: Path,
    *,
    title: str,
    subtitle: str,
    totals: dict,
    rows: list[dict],
    limit: int = 250,
):
    """
    Mantém assinatura; melhora layout (cards + tabela completa com quebra/paginação).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    styles = _build_styles()

    entradas = _as_float(totals.get("entradas"))
    saidas = _as_float(totals.get("saidas"))
    saldo = _as_float(totals.get("saldo"))

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=MARGIN_L,
        rightMargin=MARGIN_R,
        topMargin=26 * mm,
        bottomMargin=18 * mm,
        title=title,
        author="ERP Financeiro",
    )

    story = []
    story.append(Spacer(1, 6))

    # cards KPIs
    story.append(_kpi_cards(styles, entradas=entradas, saidas=saidas, saldo=saldo))
    story.append(Spacer(1, 10))

    total_regs = len(rows or [])
    take = min(limit, total_regs)

    story.append(
        KeepTogether(
            [
                Paragraph("Lançamentos exportados", styles["H2X"]),
                Paragraph(f"Mostrando <b>{take}</b> de <b>{total_regs}</b> registros.", styles["SubX"]),
                Spacer(1, 6),
            ]
        )
    )

    header = ["Data", "Compet.", "Tipo", "Descrição", "Status", "Valor"]
    body = []

    for r in (rows or [])[:limit]:
        dt = str(r.get("entry_date", "") or "")
        comp = str(r.get("competence_month", "") or "")
        tipo = _kind_label(r.get("kind"))
        desc_text = str(r.get("description", "") or "")
        doc_no = str(r.get("document_number", "") or "").strip()
        if doc_no:
            desc_text = f"{desc_text} (Doc: {doc_no})"
        desc = Paragraph(desc_text, styles["Cell"])
        status = str(r.get("status", "") or "")
        val = _as_float(r.get("amount"))
        body.append(
            [
                Paragraph(dt, styles["CellCenter"]),
                Paragraph(comp, styles["CellCenter"]),
                Paragraph(tipo, styles["CellCenter"]),
                desc,
                Paragraph(status, styles["CellCenter"]),
                Paragraph(_money_br(abs(val)), styles["CellRight"]),
            ]
        )

    usable_w = PAGE_W - MARGIN_L - MARGIN_R
    # larguras equilibradas (descrição leva mais espaço)
    col_widths = [
        20 * mm,   # data
        18 * mm,   # competência
        18 * mm,   # tipo
        usable_w - (20 + 18 + 18 + 22 + 26) * mm,  # descrição
        22 * mm,   # status
        26 * mm,   # valor
    ]

    story.append(_build_table(styles, header, body, col_widths))

    # nota final
    story.append(Spacer(1, 6))
    story.append(Paragraph("Dica: use o filtro de período no painel para gerar exports mais específicos.", styles["SmallMuted"]))

    doc.build(story, onFirstPage=_header_footer(title, subtitle), onLaterPages=_header_footer(title, subtitle))
