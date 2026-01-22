from fastapi import Request, HTTPException, Depends
from sqlalchemy.orm import Session
from app.core.deps import get_db
from app.models.user import User

def current_user(request: Request, db: Session) -> User:
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="Não autenticado")
    user = db.query(User).filter(User.id == int(uid)).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Não autenticado")
    return user

def require_login(request: Request, db: Session = Depends(get_db)) -> User:
    return current_user(request, db)

def require_role(*roles: str):
    def _dep(request: Request, db: Session = Depends(get_db)) -> User:
        u = current_user(request, db)
        if u.role not in roles:
            raise HTTPException(status_code=403, detail="Sem permissão")
        return u
    return _dep
