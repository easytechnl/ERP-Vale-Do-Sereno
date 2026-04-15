import random
from datetime import date
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.models.receber import Installment
from app.models.boletos import Boleto, CnabRemittance, CnabReturnImport, CnabEvent
from app.models.boletos_pagar import BoletoAPagar
from app.core.storage import competence_dir, write_bytes
from app.modules.boletos.pdf import generate_boleto_pdf
from app.modules.boletos.cnab.adapters import stub as cnab_adapter
from app.models.bancos import BankAccount
from app.models.lancamentos import LedgerEntry


_BOLETOS_PAGAR_SCHEMA_OK = False


def ensure_boletos_pagar_schema(db: Session) -> None:
    """Garante colunas novas em bases antigas sem migração formal."""
    global _BOLETOS_PAGAR_SCHEMA_OK
    if _BOLETOS_PAGAR_SCHEMA_OK:
        return

    bind = db.get_bind()
    insp = inspect(bind)
    try:
        cols = {c["name"] for c in insp.get_columns(BoletoAPagar.__tablename__)}
    except Exception:
        return

    changed = False
    if "numero_nota_fiscal" not in cols:
        if bind.dialect.name == "sqlite":
            db.execute(text("ALTER TABLE boletos_a_pagar ADD COLUMN numero_nota_fiscal VARCHAR(80)"))
        else:
            db.execute(text("ALTER TABLE boletos_a_pagar ADD COLUMN IF NOT EXISTS numero_nota_fiscal VARCHAR(80)"))
        changed = True

    if changed:
        try:
            db.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_boletos_a_pagar_numero_nota_fiscal "
                    "ON boletos_a_pagar (numero_nota_fiscal)"
                )
            )
        except Exception:
            db.rollback()
            return
        db.commit()

    _BOLETOS_PAGAR_SCHEMA_OK = True


def _fake_linha_digitavel() -> str:
    # placeholder
    nums = "".join(str(random.randint(0, 9)) for _ in range(47))
    return f"{nums[:5]}.{nums[5:10]} {nums[10:15]}.{nums[15:21]} {nums[21:26]}.{nums[26:32]} {nums[32]} {nums[33:47]}"

def _fake_barcode() -> str:
    return "".join(str(random.randint(0, 9)) for _ in range(44))

def generate_boletos_for_competence(db: Session, competence: str) -> dict:
    installments = db.query(Installment).filter(Installment.competence_month == competence).all()
    created = 0
    skipped = 0

    for inst in installments:
        exists = db.query(Boleto).filter(Boleto.installment_id == inst.id).first()
        if exists:
            skipped += 1
            continue

        nosso_numero = f"{competence.replace('-', '')}{inst.id:06d}"
        linha = _fake_linha_digitavel()
        barcode = _fake_barcode()

        boleto = Boleto(
            installment_id=inst.id,
            nosso_numero=nosso_numero,
            digitable_line=linha,
            barcode=barcode,
            due_date=inst.due_date,
            amount=float(inst.amount),
            status="EMITIDA",
        )
        db.add(boleto)
        db.flush()

        # PDF
        out_dir = competence_dir(competence) / "boletos"
        pdf_path = out_dir / f"boleto_{boleto.id}_{nosso_numero}.pdf"

        # resolve sacado
        sacado = inst.receivable.customer.name if inst.receivable and inst.receivable.customer else "Sacado"
        generate_boleto_pdf(
            pdf_path,
            sacado=sacado,
            competencia=competence,
            vencimento=inst.due_date.isoformat(),
            valor=f"{float(inst.amount):.2f}",
            linha=linha,
            nosso_numero=nosso_numero,
        )
        boleto.pdf_path = str(pdf_path)
        inst.status = "EMITIDA"

        created += 1

    db.commit()
    return {"created": created, "skipped": skipped, "total_installments": len(installments)}

def generate_cnab_remittance(db: Session, competence: str) -> dict:
    boletos = db.query(Boleto).join(Installment).filter(Installment.competence_month == competence).all()
    payload = [{
        "id": b.id,
        "nosso_numero": b.nosso_numero,
        "amount": float(b.amount),
        "due_date": b.due_date.isoformat(),
    } for b in boletos]

    file_bytes = cnab_adapter.generate_remittance(payload, params={})
    out_dir = competence_dir(competence) / "cnab"
    out_path = out_dir / f"remessa_{competence}.txt"
    write_bytes(out_path, file_bytes)

    rem = CnabRemittance(competence_month=competence, status="GERADA", file_path=str(out_path))
    db.add(rem)
    db.commit()
    db.refresh(rem)
    return {"remittance_id": rem.id, "file_path": rem.file_path, "boletos": len(boletos)}

def import_cnab_return(db: Session, competence: str, file_path: str, file_bytes: bytes) -> dict:
    # salva arquivo
    out_dir = competence_dir(competence) / "cnab"
    out_path = out_dir / f"retorno_{competence}_{date.today().isoformat()}.txt"
    write_bytes(out_path, file_bytes)

    imp = CnabReturnImport(competence_month=competence, file_path=str(out_path), summary_json=None)
    db.add(imp)
    db.commit()
    db.refresh(imp)

    events = cnab_adapter.parse_return(file_bytes, params={})
    paid = 0
    created_events = 0

    # conta padrão para lançar recebimentos (MVP)
    default_account = db.query(BankAccount).filter(BankAccount.is_active == True).order_by(BankAccount.id.asc()).first()  # noqa: E712

    for ev in events:
        boleto = db.query(Boleto).filter(Boleto.nosso_numero == ev.nosso_numero).first()
        if boleto:
            boleto.status = "PAGA"
            # baixa parcela
            inst = db.query(Installment).filter(Installment.id == boleto.installment_id).first()
            if inst:
                inst.status = "BAIXADA"
                inst.paid_at = ev.paid_at
                # cria lançamento de entrada (idempotente por nosso_numero)
                existing_le = (
                    db.query(LedgerEntry)
                    .filter(
                        LedgerEntry.competence_month == inst.competence_month,
                        LedgerEntry.kind == "ENTRADA",
                        LedgerEntry.description == f"Recebimento boleto {boleto.nosso_numero}",
                    )
                    .first()
                )
                if not existing_le:
                    cust_id = inst.receivable.customer_id if inst.receivable else None
                    db.add(
                        LedgerEntry(
                            competence_month=inst.competence_month,
                            entry_date=ev.paid_at or inst.due_date,
                            kind="ENTRADA",
                            status="REALIZADO",
                            amount=float(ev.paid_amount or inst.amount),
                            description=f"Recebimento boleto {boleto.nosso_numero}",
                            category="Mensalidade",
                            cost_center=None,
                            bank_account_id=default_account.id if default_account else None,
                            customer_id=cust_id,
                        )
                    )
            paid += 1

        ce = CnabEvent(
            return_import_id=imp.id,
            boleto_id=boleto.id if boleto else None,
            occurrence_code=ev.occurrence_code,
            occurrence_desc=ev.occurrence_desc,
            paid_amount=ev.paid_amount,
            paid_at=ev.paid_at,
            raw_line=ev.raw_line
        )
        db.add(ce)
        created_events += 1

    imp.summary_json = {"events": created_events, "paid_matched": paid}
    db.commit()
    return {"return_import_id": imp.id, "events": created_events, "paid_matched": paid, "stored_as": str(out_path)}
