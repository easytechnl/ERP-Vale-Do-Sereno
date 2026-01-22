from sqlalchemy.orm import Session
from app.core.db import SessionLocal
from app.core.config import settings
from app.modules.auth.service import ensure_user

def main():
    db: Session = SessionLocal()
    try:
        u = ensure_user(
            db,
            name=settings.ADMIN_NAME,
            email=settings.ADMIN_EMAIL.strip().lower(),
            password=settings.ADMIN_PASSWORD,
            role="admin",
        )
        print(f"OK: admin pronto -> {u.email} (role={u.role})")
    finally:
        db.close()

if __name__ == "__main__":
    main()
