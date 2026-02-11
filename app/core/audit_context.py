import contextvars

audit_user_id = contextvars.ContextVar("audit_user_id", default=None)
audit_ip = contextvars.ContextVar("audit_ip", default=None)
