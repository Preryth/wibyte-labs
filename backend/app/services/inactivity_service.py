from backend.app import config
from contextlib import closing
import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta, timezone

import docker

from backend.app.db.database import engine
from backend.app.services.git_service import GitService
from backend.app.services.single_lab_service import student_lab_lock

log = logging.getLogger(__name__)


class InactivityService:
    """Save and close inactive labs after the configured idle timeout."""

    INACTIVITY_TIMEOUT = timedelta(minutes=config.IDLE_MINUTES)

    def __init__(self, docker_client, db_path=None):
        self.docker_client = docker_client
        self.db_path = db_path or engine.url.database
        self.git_service = GitService(docker_client)
        with closing(sqlite3.connect(self.db_path, timeout=30)) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS lab_timeout_events (
                    lab_id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    message TEXT NOT NULL,
                    pushed INTEGER NOT NULL DEFAULT 0,
                    commit_created INTEGER NOT NULL DEFAULT 0
                )
            """)
            db.commit()

    @staticmethod
    def as_utc(value):
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc)

    def gui_last_activity(self, container):
        if container.status != "running":
            return None

        result = container.exec_run(
            [
                "sh", "-lc",
                "pgrep -x Xvfb >/dev/null; state=$?; "
                'if [ "$state" -eq 1 ]; then echo NO_GUI; '
                'elif [ "$state" -ne 0 ]; then exit "$state"; '
                "else DISPLAY=:1 timeout 3s xprintidle; fi",
            ],
            user="student",
        )
        if result.exit_code != 0:
            raise RuntimeError(
                "Cannot measure GUI activity: "
                + result.output.decode("utf-8", errors="replace")
            )

        output = result.output.decode().strip()
        if output == "NO_GUI":
            return None

        idle_ms = int(output)
        if idle_ms < 0:
            raise RuntimeError("Invalid GUI idle time")
        return datetime.now(timezone.utc) - timedelta(milliseconds=idle_ms)

    def session_status(self, lab_id, student_id):
        with closing(sqlite3.connect(self.db_path, timeout=30)) as db:
            row = db.execute(
                "SELECT status FROM labs WHERE id = ? AND student_id = ?",
                (lab_id, student_id),
            ).fetchone()
            event = db.execute(
                "SELECT outcome, message FROM lab_timeout_events "
                "WHERE lab_id = ? AND student_id = ?",
                (lab_id, student_id),
            ).fetchone()
        if row:
            return {
                "lab_id": lab_id,
                "status": row[0],
                "timeout_outcome": event[0] if event else None,
                "message": event[1] if event else None,
            }
        if event:
            return {
                "lab_id": lab_id, "status": "terminated",
                "timeout_outcome": event[0], "message": event[1],
            }
        return None

    def cleanup_lab(self, lab_id, container_id, *, force=False):
        with closing(sqlite3.connect(self.db_path, timeout=30)) as db:
            row = db.execute(
                "SELECT student_id FROM labs WHERE id = ? AND container_id = ?",
                (lab_id, container_id),
            ).fetchone()
        if row is None:
            return False
        with student_lab_lock(row[0]):
            return self._cleanup_locked(lab_id, container_id, force=force)

    def _cleanup_locked(self, lab_id, container_id, *, force=False):
        try:
            container = self.docker_client.containers.get(container_id)
        except docker.errors.NotFound:
            container = None

        if force and container is None:
            return False
        gui_activity = self.gui_last_activity(container) if container and not force else None
        db = sqlite3.connect(self.db_path, timeout=30)
        frozen = False
        removed = False
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT student_id, status, last_activity_at, github_repository_id, "
                "EXISTS(SELECT 1 FROM github_connections g "
                "WHERE g.student_id = labs.student_id) "
                "FROM labs WHERE id = ? AND container_id = ?",
                (lab_id, container_id),
            ).fetchone()
            if row is None or row[1] not in ("running", "auto_saving"):
                return False

            owner, status, timestamp, repository_id, github_connected = row
            last_activity = self.as_utc(timestamp)
            if status == "running":
                if gui_activity and gui_activity > last_activity:
                    last_activity = gui_activity
                    db.execute(
                        "UPDATE labs SET last_activity_at = ? WHERE id = ?",
                        (last_activity.replace(tzinfo=None).isoformat(" "), lab_id),
                    )
                cutoff = datetime.now(timezone.utc) - self.INACTIVITY_TIMEOUT
                if last_activity > cutoff and not force:
                    db.commit()
                    return False

            db.execute(
                "INSERT OR IGNORE INTO lab_timeout_events "
                "(lab_id, student_id, outcome, message) VALUES (?, ?, ?, ?)",
                (lab_id, owner, "saving", "Saving work before inactivity timeout."),
            )
            db.execute("UPDATE labs SET status = 'auto_saving' WHERE id = ?", (lab_id,))
            db.execute(
                "UPDATE lab_timeout_events SET outcome = 'saving', message = ? "
                "WHERE lab_id = ?",
                ("Saving work before inactivity timeout.", lab_id),
            )
            db.commit()

            event = db.execute(
                "SELECT pushed, commit_created FROM lab_timeout_events WHERE lab_id = ?",
                (lab_id,),
            ).fetchone()
            pushed, committed = bool(event[0]), bool(event[1])

            if container is None:
                if not pushed:
                    message = (
                        "The lab is no longer available. Its files could not be "
                        "automatically committed or pushed."
                    )
                    outcome = "unavailable"
                else:
                    message = self._success_message(committed, force=force)
                    outcome = "saved"
            elif not github_connected and not force:
                message = (
                    "Your lab was closed due to inactivity. No GitHub account "
                    "was connected, so no commit or push was made."
                )
                outcome = "terminated_no_github"
                container.remove(force=True)
                removed = True
            else:
                if not repository_id:
                    raise RuntimeError("No GitHub repository is connected.")

                # Freeze student programs while Git captures the final saved files.
                result = container.exec_run(
                    ["pkill", "-STOP", "-u", "student"], user="root"
                )
                if result.exit_code not in (0, 1):
                    raise RuntimeError("Could not freeze student programs.")
                frozen = True

                git = self.git_service
                git_status = git.status(lab_id)
                if not git_status["clean"]:
                    git.commit(
                        lab_id,
                        "Auto-save before administrator termination"
                        if force else "Auto-save due to lab inactivity",
                    )
                    committed = True
                    db.execute(
                        "UPDATE lab_timeout_events SET commit_created = 1 WHERE lab_id = ?",
                        (lab_id,),
                    )
                    db.commit()

                # Push even if tracking information is missing.
                lab, student, repository = git._assert_repository(lab_id)
                branch = git._run(container_id, ["git", "branch", "--show-current"])
                if not branch:
                    raise RuntimeError("Cannot push from a detached HEAD.")
                git._run(
                    container_id,
                    ["timeout", "30s", *git._credential_command(
                        ["push", "origin", f"HEAD:refs/heads/{branch}"]
                    )],
                    environment=git._remote_environment(student.id),
                )

                # Verify the remote contains exactly the commit being preserved.
                head = git._run(container_id, ["git", "rev-parse", "HEAD"])
                remote = git._run(
                    container_id,
                    ["timeout", "30s", *git._credential_command(
                        ["ls-remote", "origin", f"refs/heads/{branch}"]
                    )],
                    environment=git._remote_environment(student.id),
                )
                if not remote or remote.split()[0] != head:
                    raise RuntimeError("Could not verify the pushed commit.")
                if not git.status(lab_id)["clean"]:
                    raise RuntimeError("Files changed while saving; preserving the lab.")

                message = self._success_message(committed, force=force)
                destination = getattr(repository, "full_name", None)
                if destination:
                    message += f" Repository: {destination}."
                outcome = "saved"
                db.execute(
                    "UPDATE lab_timeout_events SET pushed = 1, message = ? WHERE lab_id = ?",
                    (message, lab_id),
                )
                db.commit()

                container.remove(force=True)
                removed = True

            # Keep the notice after deleting the lab record.
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE lab_timeout_events SET outcome = ?, message = ? WHERE lab_id = ?",
                (outcome, message, lab_id),
            )
            db.execute(
                "DELETE FROM labs WHERE id = ? AND container_id = ?",
                (lab_id, container_id),
            )
            db.commit()
            try:
                from backend.app.services.admin_store import activity
                activity(
                    "lab.admin_save_close" if force else "lab.inactivity_close", target=lab_id,
                    outcome="success" if outcome in ("saved", "terminated_no_github") else "failed",
                    details={"student_id": owner, "save_outcome": outcome},
                )
            except Exception:
                log.warning("Could not record inactivity history for %s", lab_id)
            log.warning("Closed inactive lab %s; result=%s", lab_id, outcome)
            return True
        except Exception as exc:
            db.rollback()
            db.execute(
                "UPDATE labs SET status = 'running' WHERE id = ? AND container_id = ?",
                (lab_id, container_id),
            )
            db.execute(
                "UPDATE lab_timeout_events SET outcome = 'save_failed', message = ? "
                "WHERE lab_id = ?",
                (
                    "Automatic saving to GitHub could not be completed. "
                    "Your lab has been kept so you can retry Commit & Push.",
                    lab_id,
                ),
            )
            db.commit()
            # Avoid logging Git output that could contain credentials.
            try:
                from backend.app.services.admin_store import activity
                activity(
                    "lab.admin_save" if force else "lab.inactivity_save",
                    target=lab_id, outcome="failed",
                )
            except Exception:
                log.warning("Could not record inactivity history for %s", lab_id)
            log.warning("Inactivity save failed for %s (%s); preserving lab",
                        lab_id, type(exc).__name__)
            return False
        finally:
            if frozen and not removed:
                try:
                    container.exec_run(["pkill", "-CONT", "-u", "student"], user="root")
                except Exception:
                    log.warning("Could not resume student programs in %s", lab_id)
            db.close()

    @staticmethod
    def _success_message(committed, *, force=False):
        if force:
            return (
                "Your lab was closed by an administrator. Saved files were "
                "committed and pushed to GitHub before closing."
                if committed else
                "Your lab was closed by an administrator. All saved work was "
                "verified as pushed to GitHub before closing; no new commit was needed."
            )
        if committed:
            return (
                "Your lab was closed due to inactivity. Saved files were "
                "automatically committed and pushed to GitHub before closing. "
                "Commit: Auto-save due to lab inactivity."
            )
        return (
            "Your lab was closed due to inactivity. All saved work was verified "
            "as pushed to GitHub before closing; no new commit was needed."
        )

    def cleanup_inactive_labs(self):
        with closing(sqlite3.connect(self.db_path, timeout=30)) as db:
            rows = db.execute(
                "SELECT id, container_id, status, last_activity_at "
                "FROM labs WHERE status IN ('running', 'auto_saving')"
            ).fetchall()

        cutoff = datetime.now(timezone.utc) - self.INACTIVITY_TIMEOUT
        removed = 0
        for lab_id, container_id, status, timestamp in rows:
            try:
                if status == "auto_saving" or self.as_utc(timestamp) <= cutoff:
                    removed += int(self.cleanup_lab(lab_id, container_id))
            except Exception as exc:
                log.warning("Cleanup deferred for %s (%s)", lab_id, type(exc).__name__)
        return removed

    async def run_forever(self):
        while True:
            try:
                await asyncio.to_thread(self.cleanup_inactive_labs)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Inactivity scan failed; will retry")
            await asyncio.sleep(60)
