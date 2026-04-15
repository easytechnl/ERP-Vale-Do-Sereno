from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.core.utils import COMPETENCE_MAX, COMPETENCE_MIN, CompetenceValidationError

templates = Jinja2Templates(directory="app/templates")


def _brl(value) -> str:
    """Formata valor numérico para moeda pt-BR (1.234,56)."""
    try:
        v = float(value or 0)
    except Exception:
        return str(value)
    s = f"{v:,.2f}"  # 1,234.56
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _competence_br(value: str | None) -> str:
    """Formata competência para exibição: YYYY-MM -> MM/YYYY (pt-BR)."""
    if not value:
        return ""
    v = str(value).strip()
    # já está em MM/AAAA
    if "/" in v:
        p = v.split("/")
        if len(p) >= 2 and p[0].isdigit() and p[1].isdigit():
            return f"{p[0].zfill(2)}/{p[1]}"
    # padrão ISO YYYY-MM
    if "-" in v:
        p = v.split("-")
        if len(p) >= 2 and len(p[0]) == 4 and p[0].isdigit():
            return f"{p[1].zfill(2)}/{p[0]}"
    return v


templates.env.filters["competence_br"] = _competence_br
templates.env.filters["brl"] = _brl
templates.env.filters["brl"] = _brl
templates.env.globals["competence_min"] = COMPETENCE_MIN
templates.env.globals["competence_max"] = COMPETENCE_MAX


def register_exception_handlers(app):
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 401:
            # redireciona para login
            return HTMLResponse(
                "<script>window.location='/login';</script>",
                status_code=401,
            )
        return templates.TemplateResponse(
            "errors/http_error.html",
            {"request": request, "status_code": exc.status_code, "detail": exc.detail},
            status_code=exc.status_code,
        )

    @app.exception_handler(CompetenceValidationError)
    async def competence_exception_handler(request: Request, exc: CompetenceValidationError):
        accepts = (request.headers.get("accept") or "").lower()
        wants_json = request.url.path.startswith("/api/") or "application/json" in accepts
        if wants_json:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        return templates.TemplateResponse(
            "errors/http_error.html",
            {"request": request, "status_code": 400, "detail": str(exc)},
            status_code=400,
        )
