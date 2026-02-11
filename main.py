from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from starlette.middleware.sessions import SessionMiddleware

from pathlib import Path

from app.core.config import settings
from app.core.templating import register_exception_handlers
from app.core.audit_context import audit_user_id, audit_ip
from app.modules.auth.router import router as auth_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.cadastros.router import router as cadastros_router
from app.modules.receber.router import router as receber_router
from app.modules.boletos.router import router as boletos_router
from app.modules.conciliacao.router import router as conciliacao_router
from app.modules.relatorios.router import router as relatorios_router
from app.modules.email.router import router as email_router
from app.modules.lancamentos.router import router as lancamentos_router
from app.modules.configuracoes.router import router as configuracoes_router
from app.modules.email.automation import start_email_automation, stop_email_automation

app = FastAPI(title="ERP Financeiro (MVP)")

@app.middleware("http")
async def audit_context_middleware(request, call_next):
    session = getattr(request, "session", {}) or {}
    token_user = audit_user_id.set(session.get("user_id"))
    token_ip = audit_ip.set(request.client.host if request.client else None)
    try:
        response = await call_next(request)
    finally:
        audit_user_id.reset(token_user)
        audit_ip.reset(token_ip)
    return response

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    session_cookie=settings.SESSION_COOKIE_NAME,
    https_only=False,  # ajuste em produção
    same_site="lax",
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """Evita 404 em favicon e reduz ruído de log em dev."""
    path = Path("app/static/favicon.ico")
    if path.exists():
        return FileResponse(path)
    return Response(status_code=204)

# Routers
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(cadastros_router)
app.include_router(receber_router)
app.include_router(lancamentos_router)
app.include_router(boletos_router)
app.include_router(conciliacao_router)
app.include_router(relatorios_router)
app.include_router(email_router)
app.include_router(configuracoes_router)

register_exception_handlers(app)


@app.on_event("startup")
def on_startup():
    start_email_automation()


@app.on_event("shutdown")
def on_shutdown():
    stop_email_automation()
