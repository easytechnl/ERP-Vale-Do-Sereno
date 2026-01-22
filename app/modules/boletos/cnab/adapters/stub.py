"""Adapter CNAB (stub)

Este adapter NÃO gera CNAB válido.
Ele existe para você plugar a lógica real por banco/layout (CNAB240/400).

Contrato esperado:
- generate_remittance: recebe boletos e retorna bytes do arquivo de remessa
- parse_return: recebe bytes do arquivo de retorno e retorna eventos (pagos/ocorrências)
"""

from dataclasses import dataclass
from datetime import date

@dataclass
class ReturnEvent:
    nosso_numero: str
    occurrence_code: str
    occurrence_desc: str
    paid_amount: float | None = None
    paid_at: date | None = None
    raw_line: str | None = None

def generate_remittance(boletos: list[dict], params: dict) -> bytes:
    lines = []
    lines.append(f"REMESSA_STUB;boletos={len(boletos)}")
    for b in boletos:
        lines.append(f"BOLETO;nosso_numero={b['nosso_numero']};valor={b['amount']};venc={b['due_date']}")
    lines.append("FIM")
    return ("\n".join(lines) + "\n").encode("utf-8")


def parse_return(file_bytes: bytes, params: dict) -> list[ReturnEvent]:
    # Para demonstrar o fluxo, trate qualquer linha iniciada por 'PAGO;nosso_numero=...;valor=...;data=YYYY-MM-DD'
    text = file_bytes.decode("utf-8", errors="ignore")
    events: list[ReturnEvent] = []
    for line in text.splitlines():
        if line.startswith("PAGO;"):
            parts = dict(p.split("=", 1) for p in line.replace("PAGO;", "").split(";") if "=" in p)
            nn = parts.get("nosso_numero", "").strip()
            val = float(parts.get("valor", "0") or "0")
            dt = parts.get("data", "").strip()
            paid_at = None
            if dt:
                y, m, d = [int(x) for x in dt.split("-")]
                paid_at = date(y, m, d)
            events.append(ReturnEvent(nosso_numero=nn, occurrence_code="06", occurrence_desc="Liquidação", paid_amount=val, paid_at=paid_at, raw_line=line))
    return events
