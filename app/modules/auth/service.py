from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.core.security import verify_password, hash_password
from app.models.user import User

def authenticate(db: Session, email: str, password: str) -> User:
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")
    return user

def ensure_user(db: Session, *, name: str, email: str, password: str, role: str = "admin") -> User:
    user = db.query(User).filter(User.email == email).first()
    if user:
        return user
    user = User(name=name, email=email, password_hash=hash_password(password), role=role, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
