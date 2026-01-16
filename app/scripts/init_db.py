from app.core.db import ENGINE, SessionLocal
from app.models import Base
from app.models.bancos import BankAccount

def main():
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
