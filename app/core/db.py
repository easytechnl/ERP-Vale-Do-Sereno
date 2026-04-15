from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from app.core.config import settings


def _engine():
    connect_args = {}
    if settings.DATABASE_URL.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_engine(settings.DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)


def masked_database_url() -> str:
    try:
        return make_url(settings.DATABASE_URL).render_as_string(hide_password=True)
    except Exception:
        return settings.DATABASE_URL


def explain_database_error(exc: Exception) -> RuntimeError:
    url = masked_database_url()
    if isinstance(exc, UnicodeDecodeError) and settings.DATABASE_URL.startswith("postgresql"):
        return RuntimeError(
            "Nao foi possivel conectar ao PostgreSQL usando "
            f"{url}. No Windows, uma falha de autenticacao pode aparecer "
            "como UnicodeDecodeError quando o servidor retorna a mensagem "
            "localizada. Verifique usuario e senha no arquivo .env."
        )
    return RuntimeError(
        "Nao foi possivel inicializar a conexao com o banco usando "
        f"{url}: {exc}"
    )


ENGINE = _engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=ENGINE)

# Registers audit log hooks for all models.
import app.core.audit_events  # noqa: E402,F401
