import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from backend.app.db.database import engine

log = logging.getLogger(__name__)


@contextmanager
def connection():
    db = sqlite3.connect(engine.url.database, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize():
    with connection() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS admin_suspensions (
                student_id TEXT PRIMARY KEY,
                suspended INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                updated_by TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS admin_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at TEXT NOT NULL,
                actor_id TEXT,
                actor_email TEXT,
                action TEXT NOT NULL,
                target_id TEXT,
                outcome TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS ix_admin_activity_time
            ON admin_activity(occurred_at);

            CREATE TABLE IF NOT EXISTS admin_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                category TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                target_id TEXT,
                source_key TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS admin_notification_reads (
                notification_id INTEGER NOT NULL,
                admin_id TEXT NOT NULL,
                read_at TEXT NOT NULL,
                PRIMARY KEY(notification_id, admin_id)
            );
            CREATE TABLE IF NOT EXISTS admin_notification_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        from backend.app.services.admin_notification_service import backfill
        backfill(db)


def is_suspended(student_id):
    with connection() as db:
        row = db.execute(
            "SELECT suspended FROM admin_suspensions WHERE student_id = ?",
            (student_id,),
        ).fetchone()
        return bool(row and row["suspended"])


def activity(action, actor=None, target=None, outcome="success", details=None):
    at = datetime.now(timezone.utc).isoformat()
    actor_email = getattr(actor, "email", None)
    details = details or {}
    with connection() as db:
        cursor = db.execute(
            """INSERT INTO admin_activity
            (occurred_at, actor_id, actor_email, action, target_id, outcome, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (at, getattr(actor, "id", None), actor_email,
             action, target, outcome, json.dumps(details)),
        )
        db.execute("SAVEPOINT create_notification")
        try:
            from backend.app.services.admin_notification_service import from_activity, set_state
            from_activity(
                db, cursor.lastrowid, at, action, actor_email, target, outcome, details
            )
            set_state(db, "activity-checkpoint", str(cursor.lastrowid))
            db.execute("RELEASE create_notification")
        except Exception:
            db.execute("ROLLBACK TO create_notification")
            db.execute("RELEASE create_notification")
            log.exception("Could not create admin notification")


initialize()
