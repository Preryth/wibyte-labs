import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta, timezone

import docker

from backend.app.db.database import engine

log = logging.getLogger(__name__)


class InactivityService:
    """Remove registered labs after 30 minutes without user input."""

    INACTIVITY_TIMEOUT = timedelta(minutes=30)

    def __init__(self, docker_client, db_path=None):
        self.docker_client = docker_client
        self.db_path = db_path or engine.url.database

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

    def cleanup_lab(self, lab_id, container_id):
        try:
            container = self.docker_client.containers.get(container_id)
        except docker.errors.NotFound:
            container = None

        # A measurement failure preserves the lab and gets logged/retried.
        gui_activity = (
            self.gui_last_activity(container) if container is not None else None
        )

        db = sqlite3.connect(self.db_path, timeout=30)
        try:
            # Serialize the final decision with activity updates.
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT container_id, status, last_activity_at "
                "FROM labs WHERE id = ?",
                (lab_id,),
            ).fetchone()

            if row is None or row[0] != container_id or row[1] != "running":
                return False

            last_activity = self.as_utc(row[2])
            if gui_activity is not None and gui_activity > last_activity:
                last_activity = gui_activity
                db.execute(
                    "UPDATE labs SET last_activity_at = ? WHERE id = ?",
                    (
                        last_activity.replace(tzinfo=None).isoformat(" "),
                        lab_id,
                    ),
                )

            cutoff = datetime.now(timezone.utc) - self.INACTIVITY_TIMEOUT
            if last_activity > cutoff:
                db.commit()
                return False

            if container is not None:
                try:
                    container.remove(force=True)
                except docker.errors.NotFound:
                    pass

            # Only remove the record after Docker deletion succeeds.
            db.execute("DELETE FROM labs WHERE id = ?", (lab_id,))
            db.commit()
            log.warning("Removed inactive lab %s (%s)", lab_id, container_id[:12])
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def cleanup_inactive_labs(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        try:
            rows = db.execute(
                "SELECT id, container_id, last_activity_at "
                "FROM labs WHERE status = 'running'"
            ).fetchall()
        finally:
            db.close()

        cutoff = datetime.now(timezone.utc) - self.INACTIVITY_TIMEOUT
        removed = 0
        for lab_id, container_id, timestamp in rows:
            try:
                if self.as_utc(timestamp) <= cutoff:
                    removed += int(self.cleanup_lab(lab_id, container_id))
            except Exception:
                log.exception("Cleanup failed for lab %s; will retry", lab_id)
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
