"""Funções de hashing/verificação de senha.

Observação (Windows): bcrypt frequentemente exige binários/libpq e pode causar
erros de instalação/execução. Para o MVP, PBKDF2-SHA256 é estável, não depende
de libs nativas e não possui limite de 72 bytes.
"""

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)
