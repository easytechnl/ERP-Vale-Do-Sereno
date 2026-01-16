from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

def generate_demonstrativo_pdf(out_path: Path, *, competence: str, totals: dict, lines: list[dict]):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(out_path), pagesize=A4)
    w, h = A4

    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, h - 60, f"Demonstrativo Mensal (MVP) — Competência {competence}")

    y = h - 100
    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, f"Entradas: R$ {totals['entradas']:.2f}")
    y -= 16
    c.drawString(50, y, f"Saídas: R$ {totals['saidas']:.2f}")
    y -= 16
    c.drawString(50, y, f"Saldo: R$ {totals['saldo']:.2f}")
    y -= 24

    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Lançamentos (Realizado no mês):")
    y -= 16
    c.setFont("Helvetica", 9)

    for ln in lines[:35]:
        val = float(ln.get('amount', 0))
        sign = "+" if val >= 0 else "-"
        c.drawString(50, y, f"{ln['date']} — {ln['name']} — {sign} R$ {abs(val):.2f}")
        y -= 12
        if y < 70:
            c.showPage()
            y = h - 60
            c.setFont("Helvetica", 9)

    c.showPage()
    c.save()


def generate_periodo_pdf(out_path: Path, *, data: dict):
    """PDF simples de resumo por período (1/6/12 meses)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(out_path), pagesize=A4)
    w, h = A4

    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, h - 60, "Relatório por Período (MVP)")
    c.setFont("Helvetica", 10)
    c.drawString(50, h - 80, f"Período: {data['start']} a {data['end']} ({data['months']} mês(es))")

    t = data["totals"]
    y = h - 120
    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, f"Entradas: R$ {t['entradas']:.2f}")
    y -= 16
    c.drawString(50, y, f"Saídas: R$ {t['saidas']:.2f}")
    y -= 16
    c.drawString(50, y, f"Saldo: R$ {t['saldo']:.2f}")
    y -= 28

    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Série mensal:")
    y -= 16
    c.setFont("Helvetica", 9)
    for row in data.get("series", [])[:36]:
        c.drawString(50, y, f"{row['competence']} — Entradas R$ {row['entradas']:.2f} | Saídas R$ {row['saidas']:.2f} | Saldo R$ {row['saldo']:.2f}")
        y -= 12
        if y < 70:
            c.showPage()
            y = h - 60
            c.setFont("Helvetica", 9)

    c.showPage()
    c.save()
