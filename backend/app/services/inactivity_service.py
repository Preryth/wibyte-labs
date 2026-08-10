import asyncio
from datetime import datetime, timedelta, timezone

import docker

from backend.app.db.database import SessionLocal
from backend.app.models.lab_db import Lab
from backend.app.services.lab_service import lab_service


class InactivityService:
    """
    Handles automatic cleanup of inactive labs.

    Current safety rule:

    A lab is only automatically deleted when:
        1. It has been inactive for at least 30 minutes.
        2. Its /workspace directory is empty.

    The second condition is temporary.

    Once GitHub integration exists, this will be replaced
    with proper saved / unsaved / pushed-work detection.
    """

    INACTIVITY_TIMEOUT = timedelta(minutes=30)

    def __init__(
        self,
        docker_client: docker.DockerClient,
    ):
        self.docker_client = docker_client

    # ---------------------------------------------------------
    # Check whether a container's workspace is empty
    # ---------------------------------------------------------

    def workspace_is_empty(
        self,
        container_id: str,
    ) -> bool:
        try:
            container = (
                self.docker_client.containers.get(
                    container_id
                )
            )

            result = container.exec_run(
                [
                    "bash",
                    "-lc",
                    (
                        "if find /workspace "
                        "-mindepth 1 "
                        "-maxdepth 1 "
                        "-print -quit | "
                        "grep -q .; "
                        "then "
                        "exit 1; "
                        "else "
                        "exit 0; "
                        "fi"
                    ),
                ]
            )

            return result.exit_code == 0

        except docker.errors.NotFound:
            # If the container is already gone, there is
            # nothing left to preserve.
            return True

        except Exception:
            # Fail closed.
            #
            # If we cannot determine the workspace state,
            # NEVER automatically delete the lab.
            return False

    # ---------------------------------------------------------
    # Delete one inactive lab
    # ---------------------------------------------------------

    def cleanup_lab(
        self,
        lab_id: str,
        container_id: str,
    ) -> bool:
        """
        Attempt to safely remove one inactive lab.

        Returns True if the lab was removed.
        Returns False if it was preserved.
        """

        # -----------------------------------------------------
        # Safety check: workspace must be empty.
        # -----------------------------------------------------

        if not self.workspace_is_empty(
            container_id
        ):
            return False

        # -----------------------------------------------------
        # Remove Docker container.
        # -----------------------------------------------------

        try:
            container = (
                self.docker_client.containers.get(
                    container_id
                )
            )

            container.remove(
                force=True
            )

        except docker.errors.NotFound:
            pass

        except Exception:
            # If Docker deletion fails, don't remove the
            # database record. That would leave the system
            # inconsistent.
            return False

        # -----------------------------------------------------
        # Remove database record.
        # -----------------------------------------------------

        removed = lab_service.remove(
            lab_id
        )

        return removed is not None

    # ---------------------------------------------------------
    # Find and clean inactive labs
    # ---------------------------------------------------------

    def cleanup_inactive_labs(self) -> int:
        """
        Find inactive labs and safely remove them.

        Returns the number of labs removed.
        """

        now = datetime.now(
            timezone.utc
        )

        cutoff = (
            now -
            self.INACTIVITY_TIMEOUT
        )

        db = SessionLocal()

        try:
            labs = (
                db.query(Lab)
                .filter(
                    Lab.status == "running",
                    Lab.last_activity_at <= cutoff,
                )
                .all()
            )

            # Copy only the information we need before
            # closing the database session.
            inactive_labs = [
                (
                    lab.id,
                    lab.container_id,
                )
                for lab in labs
            ]

        finally:
            db.close()

        removed_count = 0

        for (
            lab_id,
            container_id,
        ) in inactive_labs:

            removed = self.cleanup_lab(
                lab_id,
                container_id,
            )

            if removed:
                removed_count += 1

        return removed_count

    # ---------------------------------------------------------
    # Background worker
    # ---------------------------------------------------------

    async def run_forever(self):
        """
        Continuously check for inactive labs.

        The worker checks once every 60 seconds.
        """

        while True:

            try:
                removed_count = await asyncio.to_thread(
                    self.cleanup_inactive_labs
                )

                if removed_count:
                    print(
                        "[InactivityService] "
                        f"Removed {removed_count} "
                        "inactive lab(s)."
                    )

            except asyncio.CancelledError:
                print(
                    "[InactivityService] "
                    "Worker stopped."
                )

                raise

            except Exception as exc:
                # The worker must never die because of one
                # unexpected exception.
                print(
                    "[InactivityService] "
                    f"Cleanup error: {exc}"
                )

            await asyncio.sleep(
                60
            )