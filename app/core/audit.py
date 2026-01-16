from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.audit import AuditLog

def audit_log(db: Session, actor_user_id: int | None, entity: str, entity_id: int | None, action: str, before: dict | None = None, after: dict | None = None, ip: str | None = None):
    log = AuditLog(
        actor_user_id=actor_user_id,
        entity=entity,
        entity_id=entity_id,
        action=action,
        before_json=before,
        after_json=after,
        ip=ip,
        created_at=datetime.now(timezone.utc),
    )
    db.add(log)
