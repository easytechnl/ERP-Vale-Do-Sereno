from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi.responses import RedirectResponse


DEFAULT_SUCCESS_MESSAGE = "A\u00e7\u00e3o conclu\u00edda"
DEFAULT_ERROR_MESSAGE = "N\u00e3o foi poss\u00edvel concluir a a\u00e7\u00e3o."


def normalize_toast_kind(kind: str | None) -> str:
    value = str(kind or "").strip().lower()
    if value in {"ok", "success", "sucesso"}:
        return "ok"
    if value in {"err", "error", "erro"}:
        return "err"
    if value in {"warn", "warning", "aviso"}:
        return "warn"
    return "info"


def with_query_params(url: str, **params) -> str:
    split = urlsplit(url)
    merged = dict(parse_qsl(split.query, keep_blank_values=True))
    for key, value in params.items():
        if value is None:
            merged.pop(key, None)
            continue
        merged[str(key)] = str(value)
    return urlunsplit(
        (
            split.scheme,
            split.netloc,
            split.path,
            urlencode(merged, doseq=True),
            split.fragment,
        )
    )


def with_toast(url: str, kind: str = "ok", message: str | None = None) -> str:
    normalized_kind = normalize_toast_kind(kind)
    if message is None:
        message = DEFAULT_SUCCESS_MESSAGE if normalized_kind == "ok" else DEFAULT_ERROR_MESSAGE
    return with_query_params(url, toast=normalized_kind, toast_message=message)


def toast_redirect(
    url: str,
    *,
    kind: str = "ok",
    message: str | None = None,
    status_code: int = 303,
) -> RedirectResponse:
    return RedirectResponse(
        url=with_toast(url, kind=kind, message=message),
        status_code=status_code,
    )
