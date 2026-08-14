from __future__ import annotations


class GuiService:
    """
    Manage the on-demand graphical environment inside an existing
    Wibyte Labs Docker container.

    The Lab container itself is still created by the existing Lab
    lifecycle. This service never creates another container.

    GUI startup sequence:

        Xvfb :1
            ↓
        Fluxbox
            ↓
        x11vnc on localhost:5901
            ↓
        websockify/noVNC on :6080

    The processes are started only when requested. Because they run
    inside the existing Lab container, removing that container also
    removes the GUI environment automatically.
    """

    DISPLAY = ":1"
    SCREEN = "1440x900x24"
    VNC_PORT = 5901
    WEB_PORT = 6080
    NOVNC_WEB_ROOT = "/usr/share/novnc"

    def __init__(self, docker_client):
        self.docker_client = docker_client

    def _get_container(self, container_id: str):
        return self.docker_client.containers.get(container_id)

    def _process_command(self, container, process_name: str) -> bool:
        """
        Check for a process by its executable/command name.

        This avoids relying on pgrep -f patterns containing spaces,
        regex characters, or argument-order assumptions.
        """
        result = container.exec_run(
            [
                "bash",
                "-lc",
                f"pgrep -x -- '{process_name}' >/dev/null 2>&1",
            ],
            user="student",
        )
        return result.exit_code == 0

    def _is_x11vnc_running(self, container) -> bool:
        """
        Check specifically for x11vnc listening on the expected VNC port.
        """
        result = container.exec_run(
            [
                "bash",
                "-lc",
                (
                    "pgrep -x x11vnc >/dev/null 2>&1 "
                    "&& pgrep -af x11vnc "
                    f"| grep -q -- '-rfbport {self.VNC_PORT}'"
                ),
            ],
            user="student",
        )
        return result.exit_code == 0

    def _is_websockify_running(self, container) -> bool:
        """
        Check specifically for websockify listening on the expected
        noVNC/web port.
        """
        result = container.exec_run(
            [
                "bash",
                "-lc",
                (
                    "pgrep -x websockify >/dev/null 2>&1 "
                    "&& pgrep -af websockify "
                    f"| grep -q -- '{self.WEB_PORT}'"
                ),
            ],
            user="student",
        )
        return result.exit_code == 0

    def status(self, container_id: str) -> dict:
        """
        Return the current GUI-process status for one existing Lab
        container without starting anything.
        """
        container = self._get_container(container_id)
        container.reload()

        container_running = (
            container.attrs.get("State", {}).get("Running", False)
        )

        if not container_running:
            return {
                "container_running": False,
                "display": self.DISPLAY,
                "vnc_port": self.VNC_PORT,
                "xvfb_running": False,
                "fluxbox_running": False,
                "x11vnc_running": False,
                "ready": False,
            }

        xvfb_running = self._process_command(container, "Xvfb")
        fluxbox_running = self._process_command(container, "fluxbox")
        x11vnc_running = self._is_x11vnc_running(container)
        websockify_running = self._is_websockify_running(container)

        return {
            "container_running": True,
            "display": self.DISPLAY,
            "vnc_port": self.VNC_PORT,
            "web_port": self.WEB_PORT,
            "xvfb_running": xvfb_running,
            "fluxbox_running": fluxbox_running,
            "x11vnc_running": x11vnc_running,
            "websockify_running": websockify_running,
            "ready": (
                xvfb_running
                and fluxbox_running
                and x11vnc_running
                and websockify_running
            ),
        }

    def _run_checked(
        self,
        container,
        command: list[str],
        description: str,
    ) -> None:
        result = container.exec_run(
            command,
            user="student",
        )

        if result.exit_code != 0:
            detail = result.output.decode(
                "utf-8",
                errors="replace",
            ).strip()

            raise RuntimeError(
                f"{description} failed"
                + (
                    f": {detail}"
                    if detail
                    else "."
                )
            )

    def _wait_until_ready(
        self,
        container_id: str,
        attempts: int = 20,
        delay_seconds: float = 0.25,
    ) -> dict:
        """
        Poll the service's own status checks until all GUI processes
        are detected as ready.
        """
        import time

        for _ in range(attempts):
            status = self.status(container_id)

            if status["ready"]:
                return status

            time.sleep(delay_seconds)

        status = self.status(container_id)

        raise RuntimeError(
            "GUI environment did not become ready. "
            f"Current status: {status}"
        )

    def start(self, container_id: str) -> dict:
        """
        Start the GUI environment inside an existing running Lab.

        The operation is idempotent: calling it again reuses the
        existing Xvfb/Fluxbox/x11vnc/websockify processes instead of
        creating duplicates.
        """
        container = self._get_container(container_id)
        container.reload()

        if not container.attrs.get(
            "State",
            {},
        ).get(
            "Running",
            False,
        ):
            raise RuntimeError(
                "Lab container is not running."
            )

        current = self.status(container_id)

        if not current["xvfb_running"]:
            self._run_checked(
                container,
                [
                    "bash",
                    "-lc",
                    (
                        f"nohup Xvfb {self.DISPLAY} "
                        f"-screen 0 {self.SCREEN} "
                        "-nolisten tcp "
                        "> /tmp/wpl-xvfb.log 2>&1 &"
                    ),
                ],
                "Starting Xvfb",
            )

        current = self.status(container_id)

        if not current["fluxbox_running"]:
            self._run_checked(
                container,
                [
                    "bash",
                    "-lc",
                    (
                        f"nohup env DISPLAY={self.DISPLAY} fluxbox "
                        "> /tmp/wpl-fluxbox.log 2>&1 &"
                    ),
                ],
                "Starting Fluxbox",
            )

        current = self.status(container_id)

        if not current["x11vnc_running"]:
            self._run_checked(
                container,
                [
                    "bash",
                    "-lc",
                    (
                        "nohup x11vnc "
                        f"-display {self.DISPLAY} "
                        "-forever "
                        "-shared "
                        "-nopw "
                        "-localhost "
                        f"-rfbport {self.VNC_PORT} "
                        "> /tmp/wpl-x11vnc.log 2>&1 &"
                    ),
                ],
                "Starting x11vnc",
            )

        current = self.status(container_id)

        if not current["websockify_running"]:
            self._run_checked(
                container,
                [
                    "bash",
                    "-lc",
                    (
                        "nohup websockify "
                        f"--web {self.NOVNC_WEB_ROOT} "
                        f"{self.WEB_PORT} "
                        f"127.0.0.1:{self.VNC_PORT} "
                        "> /tmp/wpl-websockify.log 2>&1 &"
                    ),
                ],
                "Starting websockify/noVNC",
            )

        return self._wait_until_ready(container_id)
