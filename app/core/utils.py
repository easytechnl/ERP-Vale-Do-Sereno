from __future__ import annotations

import re


def normalize_competence(value: str | None) -> str | None:
    """Normaliza competência.

    Aceita:
      - "YYYY-MM" (padrão interno)
      - "MM/YYYY" ou "M/YYYY"
      - "MM-YYYY" ou "M-YYYY"

    Retorna "YYYY-MM" ou None.
    """
    if not value:
        return None

    v = str(value).strip()
    if not v:
        return None

    # já está no padrão interno
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", v)
    if m:
        y = int(m.group(1))
        mo = int(m.group(2))
        if 1 <= mo <= 12:
            return f"{y:04d}-{mo:02d}"

    # MM/YYYY
    m = re.fullmatch(r"(\d{1,2})[/-](\d{4})", v)
    if m:
        mo = int(m.group(1))
        y = int(m.group(2))
        if 1 <= mo <= 12:
            return f"{y:04d}-{mo:02d}"

    return v  # fallback: mantém, para não quebrar rotas/uso legado
