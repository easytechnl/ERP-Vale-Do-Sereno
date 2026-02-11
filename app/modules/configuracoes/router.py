from pathlib import Path
import csv
import io
import json
import glob
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from urllib.parse import urlparse, unquote, parse_qs

from fastapi import APIRouter, Depends, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse, FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.config import settings
from app.core.deps import get_db
from app.core.templating import templates
from app.core.utils import normalize_competence
from app.core.security import hash_password
from app.modules.auth.utils import require_login, require_role
from app.models.audit import AuditLog
from app.models.user import User

router = APIRouter(prefix="/configuracoes", tags=["configuracoes"])

SETTINGS_PATH = Path("data/configuracoes.json")

DEFAULT_SETTINGS = {
    "preferences": {
        "maintenance_notifications": True,
        "critical_events": True,
        "quiet_hours": False,
        "auto_backup": True,
        "email_reports": True,
        "auto_due_reminder_emails": False,
    },
    "status": {
        "overall": "Operacional",
        "last_check": None,
        "services": {
            "api": "Online",
            "db": "Online",
            "queue": "Online",
            "storage": "Online",
        },
    },
    "email": {
        "smtp_host": "",
        "smtp_port": "",
        "smtp_user": "",
        "smtp_pass": "",
        "smtp_from": "",
        "smtp_tls": True,
    },
    "last_backup": None,
    "last_backup_path": None,
    "last_backup_error": None,
    "last_restore": None,
    "last_restore_error": None,
}


def _merge_defaults(base: dict, defaults: dict) -> dict:
    out = dict(defaults)
    for k, v in (base or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge_defaults(v, out[k])
        else:
            out[k] = v
    return out


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            return _merge_defaults(data, DEFAULT_SETTINGS)
        except Exception:
            return DEFAULT_SETTINGS.copy()
    return DEFAULT_SETTINGS.copy()


def save_settings(data: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run_health_check(db: Session) -> dict:
    services = {
        "api": "Online",
        "db": "Online",
        "queue": "Online",
        "storage": "Online",
    }
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        services["db"] = "Offline"
    try:
        Path(settings.STORAGE_DIR).mkdir(parents=True, exist_ok=True)
    except Exception:
        services["storage"] = "Offline"
    overall = "Operacional" if all(v == "Online" for v in services.values()) else "Atenção"
    return {"overall": overall, "services": services}

def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except Exception:
        return None


def _sqlite_db_path() -> Path | None:
    url = settings.DATABASE_URL or ""
    if url.startswith("sqlite:///"):
        return Path(url.replace("sqlite:///", "", 1)).resolve()
    if url.startswith("sqlite:////"):
        return Path(url.replace("sqlite:////", "/", 1)).resolve()
    return None


def _db_kind() -> str:
    url = (settings.DATABASE_URL or "").lower()
    if url.startswith("sqlite"):
        return "sqlite"
    if url.startswith("postgres") or url.startswith("postgresql"):
        return "postgres"
    return "unknown"


def _pg_command(cmd: str) -> str | None:
    exe = f"{cmd}.exe" if os.name == "nt" else cmd
    explicit = {
        "pg_dump": (settings.PG_DUMP_PATH or os.environ.get("PG_DUMP_PATH")),
        "pg_restore": (settings.PG_RESTORE_PATH or os.environ.get("PG_RESTORE_PATH")),
        "psql": (settings.PG_PSQL_PATH or os.environ.get("PG_PSQL_PATH")),
    }.get(cmd)
    if explicit:
        p = Path(explicit)
        if p.exists():
            return str(p)
    pg_bin = settings.PG_BIN or os.environ.get("PG_BIN")
    if pg_bin:
        p = Path(pg_bin) / exe
        if p.exists():
            return str(p)
    found = shutil.which(cmd) or shutil.which(exe)
    if found:
        return found
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if not base:
                continue
            pattern = str(Path(base) / "PostgreSQL" / "*" / "bin" / exe)
            matches = glob.glob(pattern)
            if matches:
                return matches[0]
    return None


def _pg_env_from_url(url: str) -> tuple[dict, str]:
    raw = (url or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="DATABASE_URL vazio.")
    if "://" not in raw:
        raise HTTPException(status_code=400, detail="DATABASE_URL inválido.")
    if raw.startswith("postgresql+"):
        raw = "postgresql://" + raw.split("://", 1)[1]
    parsed = urlparse(raw)
    if parsed.scheme not in ("postgres", "postgresql"):
        raise HTTPException(status_code=400, detail="Banco não suportado para backup.")
    dbname = (parsed.path or "").lstrip("/")
    if not dbname:
        raise HTTPException(status_code=400, detail="DATABASE_URL sem nome do banco.")
    env = os.environ.copy()
    if parsed.hostname:
        env["PGHOST"] = parsed.hostname
    if parsed.port:
        env["PGPORT"] = str(parsed.port)
    if parsed.username:
        env["PGUSER"] = unquote(parsed.username)
    if parsed.password:
        env["PGPASSWORD"] = unquote(parsed.password)
    env["PGDATABASE"] = dbname
    qs = parse_qs(parsed.query or "")
    sslmode = (qs.get("sslmode") or [None])[0]
    if sslmode:
        env["PGSSLMODE"] = sslmode
    return env, dbname


def _run_backup() -> Path:
    kind = _db_kind()
    backup_dir = Path(settings.STORAGE_DIR) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if kind == "sqlite":
        db_path = _sqlite_db_path()
        if not db_path or not db_path.exists():
            raise HTTPException(status_code=400, detail="Backup automático disponível apenas para SQLite.")
        target = backup_dir / f"erp_backup_{stamp}.db"
        shutil.copy2(db_path, target)
        return target

    if kind == "postgres":
        target = backup_dir / f"erp_backup_{stamp}.dump"
        env, _ = _pg_env_from_url(settings.DATABASE_URL)
        pg_dump = _pg_command("pg_dump")
        if not pg_dump:
            raise HTTPException(status_code=400, detail="pg_dump não encontrado. Instale as ferramentas do PostgreSQL ou configure PG_BIN/PG_DUMP_PATH.")
        cmd = [pg_dump, "--format=custom", "--no-owner", "--file", str(target)]
        try:
            subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300, check=True)
        except FileNotFoundError:
            raise HTTPException(status_code=400, detail="pg_dump não encontrado no servidor.")
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr or exc.stdout or "").strip()
            raise HTTPException(status_code=400, detail=err or "Falha ao gerar backup PostgreSQL.")
        return target

    raise HTTPException(status_code=400, detail="Banco não suportado para backup.")


def _restore_backup_file(path: Path) -> None:
    kind = _db_kind()
    if kind == "sqlite":
        db_path = _sqlite_db_path()
        if not db_path:
            raise HTTPException(status_code=400, detail="DATABASE_URL não é SQLite.")
        from app.core.db import ENGINE
        backup_dir = Path(settings.STORAGE_DIR) / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if db_path.exists():
            shutil.copy2(db_path, backup_dir / f"pre_restore_{stamp}.db")
        ENGINE.dispose()
        shutil.copy2(path, db_path)
        return

    if kind == "postgres":
        env, dbname = _pg_env_from_url(settings.DATABASE_URL)
        suffix = path.suffix.lower()
        if suffix == ".sql":
            psql = _pg_command("psql")
            if not psql:
                raise HTTPException(status_code=400, detail="psql não encontrado. Configure PG_BIN/PG_PSQL_PATH.")
            cmd = [psql, "-d", dbname, "-f", str(path)]
        else:
            pg_restore = _pg_command("pg_restore")
            if not pg_restore:
                raise HTTPException(status_code=400, detail="pg_restore não encontrado. Configure PG_BIN/PG_RESTORE_PATH.")
            cmd = [pg_restore, "--clean", "--if-exists", "--no-owner", "--no-privileges", "-d", dbname, str(path)]
        try:
            subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=600, check=True)
        except FileNotFoundError:
            raise HTTPException(status_code=400, detail="pg_restore/psql não encontrado no servidor.")
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr or exc.stdout or "").strip()
            raise HTTPException(status_code=400, detail=err or "Falha ao restaurar backup PostgreSQL.")
        return

    raise HTTPException(status_code=400, detail="Banco não suportado para restore.")


@router.get("")
@router.get("/")
def configuracoes_home(
    request: Request,
    limit: int = 50,
    module: str | None = None,
    user_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    settings_data = load_settings()
    status = settings_data.get("status", {})
    preferences = settings_data.get("preferences", {})
    email_settings = settings_data.get("email", {})
    last_backup = settings_data.get("last_backup")
    last_backup_path = settings_data.get("last_backup_path")
    last_backup_error = settings_data.get("last_backup_error")
    last_restore = settings_data.get("last_restore")
    last_restore_error = settings_data.get("last_restore_error")
    db_kind = _db_kind()

    if not status.get("last_check"):
        health = run_health_check(db)
        now = datetime.now().strftime("%d/%m/%Y, %H:%M:%S")
        status = {
            "overall": health["overall"],
            "last_check": now,
            "services": health["services"],
        }
        settings_data["status"] = status
        save_settings(settings_data)

    q = db.query(AuditLog)
    if module:
        q = q.filter(AuditLog.entity == module)
    if user_id:
        q = q.filter(AuditLog.actor_user_id == user_id)
    dt_from = _parse_date(date_from)
    if dt_from:
        q = q.filter(AuditLog.created_at >= dt_from)
    dt_to = _parse_date(date_to)
    if dt_to:
        q = q.filter(AuditLog.created_at < dt_to + timedelta(days=1))

    logs = q.order_by(AuditLog.id.desc()).limit(min(max(limit, 10), 300)).all()

    entities = [r[0] for r in db.query(AuditLog.entity).distinct().order_by(AuditLog.entity).all()]

    users = db.query(User).order_by(User.id.asc()).all()

    return templates.TemplateResponse(
        "configuracoes/index.html",
        {
            "request": request,
            "user": user,
            "status": status,
            "preferences": preferences,
            "email_settings": email_settings,
            "last_backup": last_backup,
            "last_backup_path": last_backup_path,
            "last_backup_error": last_backup_error,
            "last_restore": last_restore,
            "last_restore_error": last_restore_error,
            "db_kind": db_kind,
            "logs": logs,
            "users": users,
            "entities": entities,
            "filters": {
                "module": module or "",
                "user_id": user_id or "",
                "date_from": date_from or "",
                "date_to": date_to or "",
            },
            "limit": limit,
        },
    )


@router.post("/status/refresh")
def refresh_status(
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    settings_data = load_settings()
    health = run_health_check(db)
    now = datetime.now().strftime("%d/%m/%Y, %H:%M:%S")
    settings_data["status"] = {
        "overall": health["overall"],
        "last_check": now,
        "services": health["services"],
    }
    save_settings(settings_data)
    return JSONResponse(settings_data["status"])


@router.post("/preferencias")
def update_preferences(
    maintenance_notifications: str | None = Form(None),
    critical_events: str | None = Form(None),
    quiet_hours: str | None = Form(None),
    auto_backup: str | None = Form(None),
    email_reports: str | None = Form(None),
    auto_due_reminder_emails: str | None = Form(None),
    user=Depends(require_login),
):
    settings_data = load_settings()
    prefs = settings_data.get("preferences", {})
    prefs.update(
        {
            "maintenance_notifications": bool(maintenance_notifications),
            "critical_events": bool(critical_events),
            "quiet_hours": bool(quiet_hours),
            "auto_backup": bool(auto_backup),
            "email_reports": bool(email_reports),
            "auto_due_reminder_emails": bool(auto_due_reminder_emails),
        }
    )
    settings_data["preferences"] = prefs
    save_settings(settings_data)
    return RedirectResponse("/configuracoes#geral", status_code=303)


@router.post("/email")
def update_email_settings(
    smtp_host: str = Form(""),
    smtp_port: str = Form(""),
    smtp_user: str = Form(""),
    smtp_pass: str = Form(""),
    smtp_from: str = Form(""),
    smtp_tls: str | None = Form(None),
    user=Depends(require_role("admin")),
):
    settings_data = load_settings()
    email_cfg = settings_data.get("email", {}) or {}

    host = (smtp_host or "").strip()
    port_raw = (smtp_port or "").strip()
    user_val = (smtp_user or "").strip()
    from_val = (smtp_from or "").strip()

    email_cfg["smtp_host"] = host
    email_cfg["smtp_user"] = user_val
    email_cfg["smtp_from"] = from_val

    if port_raw:
        try:
            email_cfg["smtp_port"] = int(port_raw)
        except ValueError:
            email_cfg["smtp_port"] = port_raw
    else:
        email_cfg["smtp_port"] = ""

    if smtp_pass.strip():
        email_cfg["smtp_pass"] = smtp_pass

    email_cfg["smtp_tls"] = bool(smtp_tls)

    settings_data["email"] = email_cfg
    save_settings(settings_data)
    return RedirectResponse("/configuracoes#email", status_code=303)


@router.post("/backup/trigger")
def trigger_backup(
    user=Depends(require_login),
):
    settings_data = load_settings()
    try:
        target = _run_backup()
        settings_data["last_backup"] = datetime.now().strftime("%d/%m/%Y, %H:%M:%S")
        settings_data["last_backup_path"] = str(target)
        settings_data["last_backup_error"] = None
    except HTTPException as exc:
        settings_data["last_backup_error"] = str(exc.detail)
    save_settings(settings_data)
    return RedirectResponse("/configuracoes#backup", status_code=303)


@router.post("/backup/restore")
def restore_backup(
    confirm_restore: str = Form(...),
    backup_file: UploadFile = File(...),
    user=Depends(require_role("admin")),
):
    settings_data = load_settings()
    confirm_val = (confirm_restore or "").strip().upper()
    if confirm_val != "RESTAURAR":
        settings_data["last_restore_error"] = "Confirmação inválida."
        save_settings(settings_data)
        return RedirectResponse("/configuracoes#backup", status_code=303)

    backup_dir = Path(settings.STORAGE_DIR) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = Path(backup_file.filename or "backup").name
    suffix = Path(filename).suffix or ""
    target = backup_dir / f"restore_{stamp}{suffix}"
    try:
        with target.open("wb") as f:
            shutil.copyfileobj(backup_file.file, f)
        _restore_backup_file(target)
        settings_data["last_restore"] = datetime.now().strftime("%d/%m/%Y, %H:%M:%S")
        settings_data["last_restore_error"] = None
    except HTTPException as exc:
        settings_data["last_restore_error"] = str(exc.detail)
    except Exception as exc:
        settings_data["last_restore_error"] = str(exc)
    save_settings(settings_data)
    return RedirectResponse("/configuracoes#backup", status_code=303)


@router.post("/limpeza")
def cleanup_data(
    competence: str | None = Form(None),
    confirm: str | None = Form(None),
    delete_ledger: str | None = Form(None),
    delete_boletos: str | None = Form(None),
    delete_installments: str | None = Form(None),
    delete_boletos_pagar: str | None = Form(None),
    delete_boletos_receber: str | None = Form(None),
    delete_notas_fiscais: str | None = Form(None),
    delete_conciliacao: str | None = Form(None),
    delete_balance_adjustments: str | None = Form(None),
    delete_logs: str | None = Form(None),
    delete_reports: str | None = Form(None),
    delete_receivables_orphans: str | None = Form(None),
    user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    comp = normalize_competence((competence or "").strip()) or (competence or "").strip()
    confirm_val = (confirm or "").strip().upper()
    any_selected = any([
        delete_ledger,
        delete_boletos,
        delete_installments,
        delete_boletos_pagar,
        delete_boletos_receber,
        delete_notas_fiscais,
        delete_conciliacao,
        delete_balance_adjustments,
        delete_logs,
        delete_reports,
        delete_receivables_orphans,
    ])

    # aceita EXCLUIR ou EXCLUIR TUDO (o escopo depende da competência)
    if confirm_val not in ("EXCLUIR", "EXCLUIR TUDO"):
        return RedirectResponse("/configuracoes?danger=err_confirm#limpeza", status_code=303)

    # Se for EXCLUIR TUDO, nÃ£o exige seleÃ§Ã£o e apaga tudo por padrÃ£o.
    if confirm_val == "EXCLUIR TUDO":
        comp = ""
        delete_ledger = delete_boletos = delete_installments = True
        delete_boletos_pagar = delete_boletos_receber = True
        delete_notas_fiscais = delete_conciliacao = True
        delete_balance_adjustments = delete_logs = delete_reports = True
        delete_receivables_orphans = True
        any_selected = True

    if not any_selected:
        return RedirectResponse("/configuracoes?danger=err_confirm#limpeza", status_code=303)

    # Se for EXCLUIR TUDO, faz limpeza total dependendo do banco
    if confirm_val == "EXCLUIR TUDO":
        try:
            if _db_kind() == "postgres":
                tables = [
                    r[0]
                    for r in db.execute(
                        text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'users'")
                    ).fetchall()
                ]
                if tables:
                    quoted = ", ".join([f"\"{t}\"" for t in tables])
                    db.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
                db.commit()
                return RedirectResponse("/configuracoes?danger=ok#limpeza", status_code=303)
        except Exception:
            db.rollback()
            return RedirectResponse("/configuracoes?danger=err_exec#limpeza", status_code=303)

    fk_off = False
    try:
        if _db_kind() == "sqlite":
            db.execute(text("PRAGMA foreign_keys=OFF"))
            fk_off = True
        # Conciliação / extrato (OFX)
        if delete_conciliacao:
            if comp:
                db.execute(text("""
                    DELETE FROM reconciliations
                    WHERE bank_transaction_id IN (
                        SELECT bt.id FROM bank_transactions bt
                        JOIN bank_statement_imports bi ON bi.id = bt.import_id
                        WHERE bi.competence_month = :c
                    )
                """), {"c": comp})
                db.execute(text("""
                    DELETE FROM bank_transactions
                    WHERE import_id IN (
                        SELECT id FROM bank_statement_imports WHERE competence_month = :c
                    )
                """), {"c": comp})
                db.execute(text("DELETE FROM bank_statement_imports WHERE competence_month = :c"), {"c": comp})
            else:
                db.execute(text("DELETE FROM reconciliations"))
                db.execute(text("DELETE FROM bank_transactions"))
                db.execute(text("DELETE FROM bank_statement_imports"))

        # Boletos gerados / CNAB
        if delete_boletos:
            if comp:
                db.execute(text("""
                    DELETE FROM cnab_events
                    WHERE boleto_id IN (
                        SELECT b.id FROM boletos b
                        JOIN installments i ON i.id = b.installment_id
                        WHERE i.competence_month = :c
                    )
                """), {"c": comp})
                db.execute(text("""
                    DELETE FROM boletos
                    WHERE installment_id IN (
                        SELECT id FROM installments WHERE competence_month = :c
                    )
                """), {"c": comp})
                db.execute(text("DELETE FROM cnab_return_imports WHERE competence_month = :c"), {"c": comp})
                db.execute(text("DELETE FROM cnab_remittances WHERE competence_month = :c"), {"c": comp})
            else:
                db.execute(text("DELETE FROM cnab_events"))
                db.execute(text("DELETE FROM boletos"))
                db.execute(text("DELETE FROM cnab_return_imports"))
                db.execute(text("DELETE FROM cnab_remittances"))

        # Parcelas/recebíveis
        if delete_installments:
            if comp:
                db.execute(text("""
                    DELETE FROM cnab_events
                    WHERE boleto_id IN (
                        SELECT b.id FROM boletos b
                        JOIN installments i ON i.id = b.installment_id
                        WHERE i.competence_month = :c
                    )
                """), {"c": comp})
                db.execute(text("""
                    DELETE FROM boletos
                    WHERE installment_id IN (
                        SELECT id FROM installments WHERE competence_month = :c
                    )
                """), {"c": comp})
                db.execute(text("DELETE FROM installments WHERE competence_month = :c"), {"c": comp})
            else:
                db.execute(text("DELETE FROM cnab_events"))
                db.execute(text("DELETE FROM boletos"))
                db.execute(text("DELETE FROM installments"))

        if delete_receivables_orphans:
            db.execute(text("""
                DELETE FROM receivables
                WHERE id NOT IN (SELECT DISTINCT receivable_id FROM installments)
            """))

        # Boletos a pagar / receber (cadastros manuais)
        if delete_boletos_pagar:
            if comp:
                db.execute(text("DELETE FROM boletos_a_pagar WHERE competence_month = :c"), {"c": comp})
            else:
                db.execute(text("DELETE FROM boletos_a_pagar"))
        if delete_boletos_receber:
            if comp:
                db.execute(text("DELETE FROM boletos_a_receber WHERE competence_month = :c"), {"c": comp})
            else:
                db.execute(text("DELETE FROM boletos_a_receber"))

        # Notas fiscais (desvincula boletos a pagar antes)
        if delete_notas_fiscais:
            if comp:
                db.execute(text("""
                    UPDATE boletos_a_pagar
                    SET nota_fiscal_id = NULL
                    WHERE nota_fiscal_id IN (
                        SELECT id FROM notas_fiscais WHERE competence_month = :c
                    )
                """), {"c": comp})
                db.execute(text("DELETE FROM notas_fiscais WHERE competence_month = :c"), {"c": comp})
            else:
                db.execute(text("UPDATE boletos_a_pagar SET nota_fiscal_id = NULL"))
                db.execute(text("DELETE FROM notas_fiscais"))

        # Lançamentos financeiros
        if delete_ledger:
            if comp:
                db.execute(text("DELETE FROM ledger_entries WHERE competence_month = :c"), {"c": comp})
            else:
                db.execute(text("DELETE FROM ledger_entries"))

        # Ajustes de saldo (prestação de contas)
        if delete_balance_adjustments:
            if comp:
                db.execute(text("DELETE FROM balance_adjustments WHERE competence_month = :c"), {"c": comp})
            else:
                db.execute(text("DELETE FROM balance_adjustments"))

        # Logs do sistema
        if delete_logs:
            db.execute(text("DELETE FROM audit_logs"))

        # Relatórios / fechamentos
        if delete_reports:
            if comp:
                db.execute(text("""
                    DELETE FROM report_snapshots
                    WHERE monthly_close_id IN (
                        SELECT id FROM monthly_closes WHERE competence_month = :c
                    )
                """), {"c": comp})
                db.execute(text("DELETE FROM monthly_closes WHERE competence_month = :c"), {"c": comp})
            else:
                db.execute(text("DELETE FROM report_snapshots"))
                db.execute(text("DELETE FROM monthly_closes"))

        db.commit()
    except Exception:
        db.rollback()
        return RedirectResponse("/configuracoes?danger=err_exec#limpeza", status_code=303)
    finally:
        if fk_off:
            try:
                db.execute(text("PRAGMA foreign_keys=ON"))
            except Exception:
                pass

    return RedirectResponse("/configuracoes?danger=ok#limpeza", status_code=303)


@router.get("/backup/download")
def download_backup(user=Depends(require_login)):
    settings_data = load_settings()
    path = settings_data.get("last_backup_path")
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="Nenhum backup disponível.")
    return FileResponse(path=path, filename=Path(path).name, media_type="application/octet-stream")


@router.get("/logs.csv")
def export_logs_csv(
    module: str | None = None,
    user_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    q = db.query(AuditLog)
    if module:
        q = q.filter(AuditLog.entity == module)
    if user_id:
        q = q.filter(AuditLog.actor_user_id == user_id)
    dt_from = _parse_date(date_from)
    if dt_from:
        q = q.filter(AuditLog.created_at >= dt_from)
    dt_to = _parse_date(date_to)
    if dt_to:
        q = q.filter(AuditLog.created_at < dt_to + timedelta(days=1))
    logs = q.order_by(AuditLog.id.desc()).limit(2000).all()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["id", "user_id", "entity", "entity_id", "action", "ip", "created_at"])
    for log in logs:
        writer.writerow([
            log.id,
            log.actor_user_id,
            log.entity,
            log.entity_id,
            log.action,
            log.ip,
            log.created_at.strftime("%d/%m/%Y %H:%M:%S") if log.created_at else "",
        ])
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(("\ufeff" + output.getvalue()).encode("utf-8")),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=logs.csv"},
    )


@router.get("/logs/live")
def live_logs(
    since_id: int | None = None,
    limit: int = 20,
    user=Depends(require_login),
    db: Session = Depends(get_db),
):
    q = db.query(AuditLog)
    if since_id:
        q = q.filter(AuditLog.id > since_id)
    logs = q.order_by(AuditLog.id.desc()).limit(min(max(limit, 5), 100)).all()
    payload = [
        {
            "id": log.id,
            "entity": log.entity,
            "action": log.action,
            "entity_id": log.entity_id,
            "actor_user_id": log.actor_user_id,
            "created_at": log.created_at.strftime("%d/%m/%Y %H:%M:%S") if log.created_at else "",
        }
        for log in logs
    ]
    last_id = payload[0]["id"] if payload else (since_id or 0)
    return {"last_id": last_id, "items": payload}


@router.post("/usuarios/create")
def create_user(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("admin"),
    user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    email_norm = email.strip().lower()
    exists = db.query(User).filter(User.email == email_norm).first()
    if exists:
        raise HTTPException(status_code=400, detail="E-mail já cadastrado.")
    new_user = User(
        name=name.strip(),
        email=email_norm,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    db.add(new_user)
    db.commit()
    return RedirectResponse("/configuracoes#usuarios", status_code=303)


@router.post("/usuarios/{user_id}/toggle")
def toggle_user(
    user_id: int,
    user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    target.is_active = not bool(target.is_active)
    db.commit()
    return RedirectResponse("/configuracoes#usuarios", status_code=303)
