from datetime import date
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.receber import Receivable, Installment

def seed_receivables_if_empty(db: Session):
    # ajuda a ver o sistema funcionando: cria 2 recebedores e 2 clientes se vazio
    if db.query(Customer).count() == 0:
        c1 = Customer(name="Cliente Exemplo 1", cpf_cnpj="000.000.000-00", email="cliente1@exemplo.com", active=True)
        c2 = Customer(name="Cliente Exemplo 2", cpf_cnpj="11.111.111/0001-11", email="cliente2@exemplo.com", active=True)
        db.add_all([c1, c2])
        db.commit()
        db.refresh(c1); db.refresh(c2)

        r1 = Receivable(customer_id=c1.id, description="Mensalidade Associação", is_recurring=True, amount=150.00, active=True)
        r2 = Receivable(customer_id=c2.id, description="Mensalidade Associação", is_recurring=True, amount=200.00, active=True)
        db.add_all([r1, r2])
        db.commit()

def generate_installments_for_competence(db: Session, competence: str, day: int = 10) -> dict:
    # competence: YYYY-MM
    year, month = [int(x) for x in competence.split("-")]
    due = date(year, month, min(day, 28))
    created = 0
    skipped = 0

    recs = db.query(Receivable).filter(Receivable.active == True).all()
    for r in recs:
        exists = db.query(Installment).filter(
            Installment.receivable_id == r.id,
            Installment.competence_month == competence
        ).first()
        if exists:
            skipped += 1
            continue
        inst = Installment(
            receivable_id=r.id,
            competence_month=competence,
            due_date=due,
            amount=float(r.amount),
            status="GERADA",
        )
        db.add(inst)
        created += 1

    db.commit()
    return {"created": created, "skipped": skipped, "due_date": due.isoformat()}
