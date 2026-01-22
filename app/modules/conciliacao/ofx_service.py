import hashlib
from datetime import date
from sqlalchemy.orm import Session
from ofxparse import OfxParser

from app.models.conciliacao import BankStatementImport, BankTransaction
from app.core.storage import competence_dir, write_bytes

def _hash_line(d: date, amount: float, memo: str) -> str:
    s = f"{d.isoformat()}|{amount:.2f}|{memo.strip().lower()}"
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:32]

def import_ofx(db: Session, competence: str, filename: str, file_bytes: bytes) -> dict:
    # salva o arquivo
    out_dir = competence_dir(competence) / "extratos"
    out_path = out_dir / filename
    write_bytes(out_path, file_bytes)

    imp = BankStatementImport(competence_month=competence, source_type="OFX", file_path=str(out_path))
    db.add(imp)
    db.commit()
    db.refresh(imp)

    # parse (OFX/QFX)
    ofx = OfxParser.parse(io_bytes(file_bytes))
    count = 0

    # ofxparse pode expor `accounts` (lista) ou `account` (single)
    accounts = getattr(ofx, "accounts", None)
    if not accounts:
        single = getattr(ofx, "account", None)
        accounts = [single] if single else []

    for acct in accounts:
        stmt = getattr(acct, "statement", None) or getattr(ofx, "statement", None)
        txns = getattr(stmt, "transactions", None) or []
        for t in txns:
            dt = t.date.date() if hasattr(t.date, "date") else t.date
            memo = (t.memo or t.payee or "")[:255]
            amount = float(t.amount)
            trn_type = str(getattr(t, "type", "") or "").upper()
            kind = "debit" if (trn_type == "DEBIT" or amount < 0) else "credit"
            amount = -abs(amount) if kind == "debit" else abs(amount)
            fit = t.id or _hash_line(dt, amount, memo)
            exists = db.query(BankTransaction).filter(BankTransaction.fit_id == fit).first()
            if exists:
                continue
            bt = BankTransaction(
                import_id=imp.id,
                txn_date=dt,
                description=memo,
                amount=amount,
                kind=kind,
                fit_id=fit,
                raw_json={"memo": t.memo, "payee": t.payee, "type": str(t.type)},
            )
            db.add(bt)
            count += 1

    db.commit()
    return {"import_id": imp.id, "stored_as": str(out_path), "transactions_created": count}


def io_bytes(b: bytes):
    import io
    return io.BytesIO(b)
