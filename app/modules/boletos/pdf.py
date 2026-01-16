from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

def generate_boleto_pdf(out_path: Path, *, sacado: str, competencia: str, vencimento: str, valor: str, linha: str, nosso_numero: str):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(out_path), pagesize=A4)
    w, h = A4
    y = h - 80
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, "BOLETO (MVP)")
    y -= 30
    c.setFont("Helvetica", 11)
    c.drawString(50, y, f"Sacado: {sacado}")
    y -= 18
    c.drawString(50, y, f"Competência: {competencia}")
    y -= 18
    c.drawString(50, y, f"Vencimento: {vencimento}")
    y -= 18
    c.drawString(50, y, f"Valor: R$ {valor}")
    y -= 18
    c.drawString(50, y, f"Nosso Número: {nosso_numero}")
    y -= 28
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Linha digitável:")
    y -= 14
    c.setFont("Helvetica", 10)
    c.drawString(50, y, linha)
    y -= 20
    c.setFont("Helvetica", 9)
    c.drawString(50, y, "Observação: Este PDF é um placeholder do MVP. Integre com CNAB/banco para boleto real.")
    c.showPage()
    c.save()
