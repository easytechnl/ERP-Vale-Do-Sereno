from sqlalchemy.orm import Session
from sqlalchemy import func, case
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


def delete_statement_import(db: Session, import_id: int) -> bool:
    """Exclui uma importação de extrato e tudo que foi gerado a partir dela.

    - Remove conciliações vinculadas às transações daquele extrato
    - Remove transações
    - Remove o registro da importação

    Retorna True se existia e foi removido.
    """

    imp = db.query(BankStatementImport).filter(BankStatementImport.id == import_id).first()
    if not imp:
        return False

    txns = db.query(BankTransaction.id).filter(BankTransaction.import_id == import_id).all()
    txn_ids = [int(t[0]) for t in txns]
    if txn_ids:
        db.query(Reconciliation).filter(Reconciliation.bank_transaction_id.in_(txn_ids)).delete(synchronize_session=False)
        db.query(BankTransaction).filter(BankTransaction.id.in_(txn_ids)).delete(synchronize_session=False)

    db.delete(imp)
    db.commit()
    return True


def statement_totals_for_competence(db: Session, competence: str) -> dict:
    """Totais (entradas/saidas/saldo) a partir do extrato importado.

    Regras:
    - Se kind estiver preenchido (credit/debit), ele é a fonte de verdade.
    - Caso kind esteja vazio, caímos no sinal do amount.
    - Se o banco enviar TRNAMT sempre positivo, mas kind=debit, isso continua correto.
    """

    last_import = (
        db.query(BankStatementImport)
        .filter(BankStatementImport.competence_month == competence)
        .order_by(BankStatementImport.id.desc())
        .first()
    )
    if not last_import:
        return {
            "has_statement": False,
            "entradas": 0.0,
            "saidas": 0.0,
            "saldo": 0.0,
            "transactions": 0,
            "last_import": None,
        }

    # IMPORTANTE:
    # Alguns bancos mandam TRNAMT sempre positivo e indicam débito/crédito via campo "kind".
    # Se o "kind" estiver presente, ele TEM prioridade. Caso contrário, usamos o sinal do amount.
    # Isso evita o bug clássico onde "entradas" passa a somar também as saídas quando TRNAMT
    # vem sempre positivo (o que deixa entradas==saídas e saldo incorreto).

    q = (
        db.query(
            func.coalesce(
                func.sum(
                    case(
                        (BankTransaction.kind == "credit", func.abs(BankTransaction.amount)),
                        (BankTransaction.kind == "debit", 0.0),
                        (BankTransaction.amount > 0, BankTransaction.amount),
                        else_=0.0,
                    )
                ),
                0.0,
            ).label("entradas"),
            func.coalesce(
                func.sum(
                    case(
                        (BankTransaction.kind == "debit", func.abs(BankTransaction.amount)),
                        (BankTransaction.kind == "credit", 0.0),
                        (BankTransaction.amount < 0, func.abs(BankTransaction.amount)),
                        else_=0.0,
                    )
                ),
                0.0,
            ).label("saidas"),
            func.coalesce(
                func.sum(
                    case(
                        (BankTransaction.kind == "debit", -func.abs(BankTransaction.amount)),
                        (BankTransaction.kind == "credit", func.abs(BankTransaction.amount)),
                        else_=BankTransaction.amount,
                    )
                ),
                0.0,
            ).label("saldo"),
            func.count(BankTransaction.id).label("transactions"),
        )
        .join(BankStatementImport, BankStatementImport.id == BankTransaction.import_id)
        .filter(BankStatementImport.competence_month == competence)
    )

    row = q.first()
    entradas = float(getattr(row, "entradas", 0.0) or 0.0)
    saidas = float(getattr(row, "saidas", 0.0) or 0.0)
    saldo = float(getattr(row, "saldo", 0.0) or 0.0)
    transactions = int(getattr(row, "transactions", 0) or 0)

    return {
        "has_statement": True,
        "entradas": float(entradas),
        "saidas": float(saidas),
        "saldo": float(saldo),
        "transactions": transactions,
        "last_import": last_import,
    }


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
