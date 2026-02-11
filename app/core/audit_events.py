from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import event
from sqlalchemy.inspection import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.core.audit_context import audit_user_id, audit_ip
from app.models.audit import AuditLog


def _model_to_dict(obj) -> dict:
    insp = sa_inspect(obj)
    data = {}
    for attr in insp.mapper.column_attrs:
        key = attr.key
        try:
            val = getattr(obj, key)
        except Exception:
            val = None
        if isinstance(val, (datetime, date)):
            val = val.isoformat()
        elif isinstance(val, Decimal):
            val = float(val)
        elif isinstance(val, bytes):
            val = val.decode("utf-8", errors="ignore")
        data[key] = val
    return data


@event.listens_for(Session, "after_flush")
def receive_after_flush(session: Session, flush_context) -> None:
    if session.info.get("audit_in_progress"):
        return

    entries: list[AuditLog] = []
    actor_id = audit_user_id.get()
    ip_addr = audit_ip.get()

    def add_entry(obj, action: str):
        if isinstance(obj, AuditLog):
            return
        insp = sa_inspect(obj)
        ident = insp.identity[0] if insp.identity else None
        entries.append(
            AuditLog(
                actor_user_id=actor_id if actor_id else None,
                entity=obj.__class__.__name__,
                entity_id=ident,
                action=action,
                before_json=None,
                after_json=_model_to_dict(obj),
                ip=ip_addr,
            )
        )

    for obj in session.new:
        add_entry(obj, "CREATE")
    for obj in session.deleted:
        add_entry(obj, "DELETE")
    for obj in session.dirty:
        if session.is_modified(obj, include_collections=False):
            add_entry(obj, "UPDATE")

    if not entries:
        return

    session.info["audit_in_progress"] = True
    try:
        for log in entries:
            session.add(log)
    finally:
        session.info["audit_in_progress"] = False
