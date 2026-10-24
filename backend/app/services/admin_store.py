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
        """)


def is_suspended(student_id):
    with connection() as db:
        row = db.execute(
            "SELECT suspended FROM admin_suspensions WHERE student_id = ?",
            (student_id,),
        ).fetchone()
        return bool(row and row["suspended"])


def activity(action, actor=None, target=None, outcome="success", details=None):
    with connection() as db:
        db.execute(
            """INSERT INTO admin_activity
            (occurred_at, actor_id, actor_email, action, target_id, outcome, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (datetime.now(timezone.utc).isoformat(),
             getattr(actor, "id", None), getattr(actor, "email", None),
             action, target, outcome, json.dumps(details or {})),
        )


initialize()
