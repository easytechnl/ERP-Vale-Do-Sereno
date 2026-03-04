from __future__ import annotations

import threading

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.email.service import is_auto_due_reminder_enabled, send_due_soon_reminders


_stop_event = threading.Event()
_worker_thread: threading.Thread | None = None


def _worker_loop():
    interval_minutes = max(int(getattr(settings, "EMAIL_REMINDER_INTERVAL_MINUTES", 60)), 5)
    startup_delay = max(int(getattr(settings, "EMAIL_REMINDER_STARTUP_DELAY_SECONDS", 20)), 0)
    if startup_delay:
        _stop_event.wait(startup_delay)

    while not _stop_event.is_set():
        db = SessionLocal()
        try:
            if is_auto_due_reminder_enabled():
                send_due_soon_reminders(db)
        except Exception as exc:
            # Não derruba a aplicação; mantém o loop ativo.
            print(f"[email-automation] reminder cycle failed: {exc}")
        finally:
            db.close()

        _stop_event.wait(interval_minutes * 60)


def start_email_automation():
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return
    _stop_event.clear()
    _worker_thread = threading.Thread(target=_worker_loop, name="email-reminder-worker", daemon=True)
    _worker_thread.start()


def stop_email_automation():
    _stop_event.set()
