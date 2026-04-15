from __future__ import annotations

import datetime as dt
import re


COMPETENCE_MIN = "2000-01"
COMPETENCE_MAX = "2100-12"


class CompetenceValidationError(ValueError):
    """Raised when a competence value cannot be safely used."""


def _competence_in_supported_range(value: str) -> bool:
    return COMPETENCE_MIN <= value <= COMPETENCE_MAX


def _competence_error(value: str | None) -> CompetenceValidationError:
    raw = str(value or "").strip()
    if not raw:
        return CompetenceValidationError("Competencia obrigatoria. Use YYYY-MM ou MM/YYYY.")

    normalized = normalize_competence(raw)
    if not normalized:
        return CompetenceValidationError("Competencia invalida. Use YYYY-MM ou MM/YYYY.")

    return CompetenceValidationError(
        f"Competencia fora do intervalo suportado ({COMPETENCE_MIN} a {COMPETENCE_MAX})."
    )


def normalize_competence(value: str | None) -> str | None:
    """Normaliza competência para o formato YYYY-MM."""
    if not value:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    match = re.fullmatch(r"(\d{4})-(\d{1,2})", raw)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}"
        return None

    match = re.fullmatch(r"(\d{1,2})[/-](\d{4})", raw)
    if match:
        month = int(match.group(1))
        year = int(match.group(2))
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}"
        return None

    return None


def supported_competence(value: str | None) -> str | None:
    normalized = normalize_competence(value)
    if not normalized:
        return None
    if _competence_in_supported_range(normalized):
        return normalized
    return None


def resolve_optional_competence(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    normalized = supported_competence(raw)
    if normalized:
        return normalized

    raise _competence_error(raw)


def resolve_competence(value: str | None, *, fallback: str | None = None) -> str:
    normalized = resolve_optional_competence(value)
    if normalized:
        return normalized

    fallback_normalized = supported_competence(fallback)
    if fallback_normalized:
        return fallback_normalized

    return current_competence()


def clamp_competence(value: str | None, fallback: str | None = None) -> str | None:
    """Deprecated compatibility alias for resolve_competence()."""
    return resolve_competence(value, fallback=fallback)


def current_competence(today: dt.date | None = None) -> str:
    base = (today or dt.date.today()).strftime("%Y-%m")
    normalized = supported_competence(base)
    if normalized:
        return normalized
    if base < COMPETENCE_MIN:
        return COMPETENCE_MIN
    return COMPETENCE_MAX
