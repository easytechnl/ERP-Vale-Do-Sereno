from sqlalchemy.orm import Session
from app.models.conciliacao import BankStatementImport, BankTransaction, Reconciliation
from app.models.receber import Installment
from app.models.boletos import Boleto

def list_transactions(db: Session, competence: str):
    imports = db.query(BankStatementImport).filter(BankStatementImport.competence_month == competence).order_by(BankStatementImport.id.desc()).all()
    txns = (
        db.query(BankTransaction)
        .join(BankStatementImport, BankStatementImport.id == BankTransaction.import_id)
        .filter(BankStatementImport.competence_month == competence)
        .order_by(BankTransaction.txn_date.asc())
        .all()
    )
    return imports, txns

def reconcile_transaction_to_installment(db: Session, bank_txn_id: int, installment_id: int) -> None:
    txn = db.query(BankTransaction).filter(BankTransaction.id == bank_txn_id).first()
    inst = db.query(Installment).filter(Installment.id == installment_id).first()
    if not txn or not inst:
        return

    # cria/atualiza conciliação
    rec = db.query(Reconciliation).filter(Reconciliation.bank_transaction_id == txn.id).first()
    if not rec:
        rec = Reconciliation(bank_transaction_id=txn.id, matched_type="installment", matched_id=inst.id, status="CONFIRMADA", confidence=100)
        db.add(rec)
    else:
        rec.matched_type = "installment"
        rec.matched_id = inst.id
        rec.status = "CONFIRMADA"

    # baixa parcela e boleto associado
    inst.status = "BAIXADA"
    b = db.query(Boleto).filter(Boleto.installment_id == inst.id).first()
    if b:
        b.status = "PAGA"

    db.commit()
