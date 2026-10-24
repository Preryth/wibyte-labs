import json
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


def state(db, key):
    row = db.execute("SELECT value FROM admin_notification_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_state(db, key, value):
    db.execute("""
        INSERT INTO admin_notification_state(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (key, value))


def notify(db, key, category, title, message, target=None, severity="info", at=None):
    db.execute("""
        INSERT OR IGNORE INTO admin_notifications
        (created_at, category, severity, title, message, target_id, source_key)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (at or now(), category, severity, title, message, target, key))


def from_activity(db, event_id, at, action, actor_email, target, outcome, details):
    if outcome == "requested":
        return
    action = action.replace("student.", "user.", 1) if action.startswith("student.") else action
    who = actor_email or "the system"
    subject = details.get("email")
    if not subject and target:
        row = db.execute("SELECT email FROM students WHERE id = ?", (target,)).fetchone()
        subject = row["email"] if row else None
    if action in ("user.request_approval", "admin.bootstrap") and not subject:
        subject = actor_email
    subject = subject or target or "an account"
    event_key = f"activity:{event_id}"

    if outcome == "success":
        phases = {
            "user.approve": "approved", "user.reject": "rejected",
            "user.request_approval": "pending", "user.delete": "deleted",
        }
        if action in phases and target:
            set_state(db, "request-phase:" + target, phases[action])

    failure_key = "save-failure:" + str(target)
    save_failures = {"lab.inactivity_save", "lab.admin_save", "lab.save_terminate"}
    if action in save_failures and outcome == "failed":
        if state(db, failure_key) != "open":
            set_state(db, failure_key, "open")
            notify(
                db, event_key, "labs", "Lab save needs attention",
                f"Lab {target} could not be saved or pushed. It was preserved for review. "
                "Repeated retries are grouped into this notification.",
                target, "error", at,
            )
        return

    resolved = {
        "git.push", "lab.close", "lab.inactivity_close",
        "lab.admin_save_close", "lab.save_terminate", "lab.discard_terminate",
    }
    if action in resolved and outcome == "success":
        was_open = state(db, failure_key) == "open"
        set_state(db, failure_key, "resolved")
        if action == "git.push":
            if was_open:
                notify(db, event_key, "labs", "Lab push recovered",
                       f"Lab {target} was successfully pushed after an earlier save failure.",
                       target, "success", at)
            return

    labels = {
        "user.approve": ("users", "Account approved", f"{subject} was approved by {who}.", "success"),
        "user.reject": ("users", "Account rejected", f"{subject} was rejected by {who}. Their account was retained.", "warning"),
        "user.suspend": ("users", "Account suspended", f"{subject} was suspended by {who}.", "warning"),
        "user.restore": ("users", "Account restored", f"{subject}'s suspension was removed by {who}.", "success"),
        "user.delete": ("users", "Account deleted", f"{subject} was permanently deleted by {who}.", "warning"),
        "user.request_approval": ("requests", "Approval requested again", f"{subject} requested approval again.", "info"),
        "admin.promote": ("admins", "Administrator added", f"{subject} was made an administrator by {who}.", "success"),
        "admin.bootstrap": ("admins", "Administrator enabled", f"Administrator access was enabled for {subject}.", "success"),
        "admin.remove": ("admins", "Administrator removed", f"{subject}'s admin role was removed by {who}. Their account was retained.", "warning"),
        "lab.save_terminate": ("labs", "Lab saved and terminated", f"{who} saved, pushed and terminated lab {target}.", "success"),
        "lab.discard_terminate": ("labs", "Lab terminated without saving", f"{who} terminated lab {target} without saving its remaining changes.", "warning"),
        "lab.close": ("labs", "Lab closed", f"{who} closed lab {target}.", "info"),
    }
    if action == "lab.inactivity_close":
        row = db.execute(
            "SELECT message FROM lab_timeout_events WHERE lab_id = ?", (target,)
        ).fetchone()
        message = row["message"] if row else f"Lab {target} closed after inactivity."
        notify(db, event_key, "labs", "Inactivity timeout", message, target,
               "info" if outcome == "success" else "warning", at)
    elif action in labels:
        category, title, message, severity = labels[action]
        if outcome != "success":
            title += " — failed"
            message = f"The action {action} for {subject} did not complete successfully."
            severity = "error"
        notify(db, event_key, category, title, message, target, severity, at)


def backfill(db):
    previous = state(db, "activity-checkpoint")
    if previous is None:
        maximum = db.execute("SELECT COALESCE(MAX(id), 0) FROM admin_activity").fetchone()[0]
        previous = str(max(0, maximum - 200))
    rows = db.execute(
        "SELECT * FROM admin_activity WHERE id > ? ORDER BY id", (int(previous),)
    ).fetchall()
    for row in rows:
        try:
            details = json.loads(row["details"])
        except (ValueError, TypeError):
            details = {}
        from_activity(
            db, row["id"], row["occurred_at"], row["action"],
            row["actor_email"], row["target_id"], row["outcome"], details,
        )
        set_state(db, "activity-checkpoint", str(row["id"]))


def observe_pending(db, profiles):
    pending_ids = {profile["id"] for profile in profiles}
    for profile in profiles:
        target = profile["id"]
        key = "request-phase:" + target
        if state(db, key) != "pending":
            at = now()
            notify(
                db, f"pending:{target}:{at}", "requests", "New approval request",
                f"{profile.get('email') or target} is waiting for approval.",
                target, "info", at,
            )
            set_state(db, key, "pending")
    tracked = db.execute(
        "SELECT key FROM admin_notification_state "
        "WHERE key LIKE 'request-phase:%' AND value = 'pending'"
    ).fetchall()
    for row in tracked:
        if row["key"].split(":", 1)[1] not in pending_ids:
            set_state(db, row["key"], "not_pending")
