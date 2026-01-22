from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.modules.conciliacao.service import statement_totals_for_competence
from app.modules.lancamentos.service import totals_for_period, series_by_month
from app.models.receber import Installment
from app.models.boletos import Boleto
from app.models.saldo import BalanceAdjustment
from app.models.customer import Customer
from app.models.receber import Receivable


def balance_adjustment_for_competence(db: Session, competence: str) -> float:
    """Soma de ajustes manuais de saldo (balance_adjustments) para a competência."""
    return float(
        db.query(func.coalesce(func.sum(BalanceAdjustment.amount), 0))
        .filter(BalanceAdjustment.competence_month == competence)
        .scalar()
        or 0.0
    )


def prev_month(competence: str) -> str:
    """Retorna YYYY-MM anterior."""
    y, m = [int(x) for x in competence.split("-")[:2]]
    d = dt.date(y, m, 1)
    prev = (d.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
    return prev.strftime("%Y-%m")


def months_back_list(competence: str, n: int = 6) -> list[str]:
    """Lista de competências (YYYY-MM) incluindo a atual, voltando n-1 meses.

    Retorna em ordem: mais antiga -> mais recente.
    """
    y, m = [int(x) for x in competence.split("-")[:2]]
    cur = dt.date(y, m, 1)
    months = []
    for i in range(n - 1, -1, -1):
        # subtrai i meses
        yy = cur.year
        mm = cur.month - i
        while mm <= 0:
            mm += 12
            yy -= 1
        months.append(f"{yy:04d}-{mm:02d}")
    return months


def boletos_stats_for_competence(db: Session, competence: str) -> dict:
    """Resumo de boletos/parcelas da competência.

    - esperado: soma das parcelas do mês
    - pago: soma dos boletos pagos vinculados a parcelas do mês
    - pendente: esperado - pago
    - vencido: boletos não pagos com vencimento < hoje
    """

    today = dt.date.today()

    installments = (
        db.query(Installment)
        .filter(Installment.competence_month == competence)
        .all()
    )
    inst_ids = [i.id for i in installments]
    expected = float(sum(float(i.amount or 0.0) for i in installments))

    paid_total = 0.0
    paid_count = 0
    pending_total = 0.0
    pending_count = 0
    overdue_total = 0.0
    overdue_count = 0

    pending_list = []

    if inst_ids:
        boletos = (
            db.query(Boleto, Installment, Receivable, Customer)
            .join(Installment, Installment.id == Boleto.installment_id)
            .join(Receivable, Receivable.id == Installment.receivable_id)
            .join(Customer, Customer.id == Receivable.customer_id)
            .filter(Boleto.installment_id.in_(inst_ids))
            .all()
        )
    else:
        boletos = []

    for (b, inst, rec, cust) in boletos:
        amt = float(b.amount or 0.0)
        status = (b.status or "").upper().strip()
        due = b.due_date

        if status == "PAGA":
            paid_total += amt
            paid_count += 1
        else:
            pending_total += amt
            pending_count += 1
            if due and isinstance(due, dt.date) and due < today:
                overdue_total += amt
                overdue_count += 1
            pending_list.append({
                "id": b.id,
                "customer_name": cust.name,
                "customer_email": cust.email,
                "due_date": b.due_date,
                "amount": float(b.amount or 0.0),
                "status": b.status,
                "nosso_numero": b.nosso_numero,
                "digitable_line": b.digitable_line,
            })

    # Caso existam parcelas sem boleto ainda, contam como pendente (pela parcela)
    inst_with_boleto = set([b.installment_id for b in boletos if b.installment_id])
    inst_without = [i for i in installments if i.id not in inst_with_boleto]
    if inst_without:
        extra = float(sum(float(i.amount or 0.0) for i in inst_without))
        pending_total += extra
        pending_count += len(inst_without)

    return {
        "expected": float(expected),
        "paid_total": float(paid_total),
        "paid_count": int(paid_count),
        "pending_total": float(max(0.0, pending_total)),
        "pending_count": int(pending_count),
        "overdue_total": float(overdue_total),
        "overdue_count": int(overdue_count),
        "pending_boletos": pending_list,
        "installments_count": int(len(installments)),
    }




def combined_totals_for_competence(db: Session, competence: str) -> dict:
    """Totais do mês somando:

    - Extrato (OFX/QFX) importado (conciliação)
    - Lançamentos manuais (ledger_entries) com status REALIZADO

    Observação: se o usuário lançar manualmente algo que também está no extrato,
    pode haver dupla contagem — é intencional, pois o requisito é que *toda*
    movimentação registrada no sistema reflita no painel e na prestação de contas.
    """

    stmt = statement_totals_for_competence(db, competence)
    ledg = totals_for_period(db, start_ym=competence, end_ym=competence, status='REALIZADO')

    entradas = float(stmt.get('entradas') or 0.0) + float(ledg.get('entradas') or 0.0)
    saidas = float(stmt.get('saidas') or 0.0) + float(ledg.get('saidas') or 0.0)

    return {
        'entradas': entradas,
        'saidas': saidas,
        'saldo': entradas - saidas,
        'has_statement': bool(stmt.get('has_statement')),
        'transactions': int(stmt.get('transactions') or 0),
        'last_import': stmt.get('last_import'),
        'ledger_entradas': float(ledg.get('entradas') or 0.0),
        'ledger_saidas': float(ledg.get('saidas') or 0.0),
        'ledger_saldo': float(ledg.get('saldo') or 0.0),
        'statement_entradas': float(stmt.get('entradas') or 0.0),
        'statement_saidas': float(stmt.get('saidas') or 0.0),
        'statement_saldo': float(stmt.get('saldo') or 0.0),
    }


def prestacao_contas_data(db: Session, competence: str) -> dict:
    prev = prev_month(competence)
    cur_totals = combined_totals_for_competence(db, competence)
    prev_totals = combined_totals_for_competence(db, prev)

    # Ajuste manual de saldo (ex.: correções/inclusões pontuais)
    cur_adj = balance_adjustment_for_competence(db, competence)
    prev_adj = balance_adjustment_for_competence(db, prev)

    cur = {
        "competence": competence,
        "entradas": float(cur_totals.get("entradas") or 0.0),
        "saidas": float(cur_totals.get("saidas") or 0.0),
        "saldo_statement": float(cur_totals.get("statement_saldo") or 0.0),
        "saldo_ledger": float(cur_totals.get("ledger_saldo") or 0.0),
        "saldo_adjustment": float(cur_adj),
        "saldo": float((cur_totals.get("saldo") or 0.0) + cur_adj),
        "has_statement": bool(cur_totals.get("has_statement")),
        "transactions": int(cur_totals.get("transactions") or 0),
    }
    prev_d = {
        "competence": prev,
        "entradas": float(prev_totals.get("entradas") or 0.0),
        "saidas": float(prev_totals.get("saidas") or 0.0),
        "saldo_statement": float(prev_totals.get("statement_saldo") or 0.0),
        "saldo_ledger": float(prev_totals.get("ledger_saldo") or 0.0),
        "saldo_adjustment": float(prev_adj),
        "saldo": float((prev_totals.get("saldo") or 0.0) + prev_adj),
        "has_statement": bool(prev_totals.get("has_statement")),
    }

    delta = {
        "entradas": cur["entradas"] - prev_d["entradas"],
        "saidas": cur["saidas"] - prev_d["saidas"],
        "saldo": cur["saldo"] - prev_d["saldo"],
        "saldo_adjustment": cur["saldo_adjustment"] - prev_d["saldo_adjustment"],
    }

    # Variação percentual do saldo (com ajuste) vs mês anterior
    saldo_var_pct = None
    if abs(prev_d["saldo"]) > 1e-9:
        saldo_var_pct = (cur["saldo"] - prev_d["saldo"]) / prev_d["saldo"] * 100.0

    boletos = boletos_stats_for_competence(db, competence)

    # Série para gráfico (últimos 6 meses)
    labels = months_back_list(competence, n=6)
    entradas_series: list[float] = []
    saidas_series: list[float] = []
    adj_series: list[float] = []
    saldo_series: list[float] = []

    for ym in labels:
        t = combined_totals_for_competence(db, ym)
        e = float(t.get("entradas") or 0.0)
        s = float(t.get("saidas") or 0.0)
        base_saldo = float(t.get("saldo") or 0.0)
        adj = float(balance_adjustment_for_competence(db, ym) or 0.0)

        entradas_series.append(e)
        saidas_series.append(s)
        adj_series.append(adj)
        saldo_series.append(base_saldo + adj)

    # Variação mês a mês do saldo final (com ajuste)
    saldo_variations = []
    prev_val = None
    for idx, ym in enumerate(labels):
        val = float(saldo_series[idx] if idx < len(saldo_series) else 0.0)
        if prev_val is None:
            delta_val = None
            delta_pct = None
        else:
            delta_val = val - prev_val
            delta_pct = None
            if abs(prev_val) > 1e-9:
                delta_pct = (delta_val / prev_val) * 100.0
        saldo_variations.append({
            "competence": ym,
            "saldo": val,
            "delta": delta_val,
            "delta_pct": delta_pct,
        })
        prev_val = val

    return {
        "current": cur,
        "previous": prev_d,
        "delta": delta,
        "saldo_var_pct": saldo_var_pct,
        "saldo_variations": saldo_variations,
        "boletos": boletos,
        "series": {
            "labels": labels,
            "entradas": entradas_series,
            "saidas": saidas_series,
            "ajustes": adj_series,
            "saldo": saldo_series,
        },
    }
