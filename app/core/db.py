from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

def _engine():
    connect_args = {}
    if settings.DATABASE_URL.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_engine(settings.DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)

ENGINE = _engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=ENGINE)

# Registers audit log hooks for all models.
import app.core.audit_events  # noqa: E402,F401
