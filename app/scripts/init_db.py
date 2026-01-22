"""Inicializa o banco e cria todas as tabelas.

Rodar no PowerShell (na raiz do projeto):

  python app/scripts/init_db.py

ou (recomendado):

  python -m app.scripts.init_db

"""


import sys
from pathlib import Path

# Garante que a raiz do projeto esteja no PYTHONPATH, mesmo quando executar via arquivo
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.db import ENGINE, SessionLocal

# IMPORTANTÍSSIMO: garantir que todos os models sejam carregados
import app.models  # executa app/models/__init__.py (carrega tudo)
import app.models.rateio  # garante rateio no metadata (mesmo que já esteja no __init__)

from app.models.base import Base
from app.models.bancos import BankAccount


def main():
    # cria todas as tabelas registradas no Base.metadata
    Base.metadata.create_all(bind=ENGINE)

    # Seed mínimo
    db = SessionLocal()
    try:
        if not db.query(BankAccount).first():
            db.add(BankAccount(name="Conta Principal", bank_name=None, opening_balance=0))
            db.commit()
            print("OK: conta bancária padrão criada (Conta Principal).")
    finally:
        db.close()

    print("OK: tabelas criadas.")


if __name__ == "__main__":
    main()
