from __future__ import annotations

import shlex


class GuiService:
    """
    Manage the on-demand graphical environment inside an existing
    Wibyte Labs Docker container.
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
        container = self._get_container(container_id)
        container.reload()

        running = container.attrs.get("State", {}).get("Running", False)

        if not running:
            return {
                "container_running": False,
                "display": self.DISPLAY,
                "vnc_port": self.VNC_PORT,
                "web_port": self.WEB_PORT,
                "xvfb_running": False,
                "fluxbox_running": False,
                "x11vnc_running": False,
                "websockify_running": False,
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

    def _start_detached(
        self,
        container,
        command: list[str],
        description: str,
        log_path: str,
        environment: dict[str, str] | None = None,
    ) -> None:
        """
        Start a long-lived GUI daemon as a detached Docker exec.

        This is more reliable than `nohup ... &` because Docker owns the
        exec process directly instead of a shell backgrounding a child.
        """
        api = container.client.api

        try:
            quoted_command = " ".join(
                shlex.quote(part)
                for part in command
            )
            shell_command = (
                f"exec {quoted_command} "
                f"> {shlex.quote(log_path)} 2>&1"
            )

            exec_instance = api.exec_create(
                container.id,
                cmd=["bash", "-lc", shell_command],
                stdout=False,
                stderr=False,
                stdin=False,
                tty=False,
                user="student",
                environment=environment,
            )
            api.exec_start(
                exec_instance["Id"],
                detach=True,
            )
        except Exception as exc:
            raise RuntimeError(f"{description} failed: {exc}") from exc

    def _wait_for_display(
        self,
        container_id: str,
        attempts: int = 20,
        delay_seconds: float = 0.1,
    ) -> None:
        import time

        for _ in range(attempts):
            container = self._get_container(container_id)
            result = container.exec_run(
                [
                    "bash",
                    "-lc",
                    f"DISPLAY={shlex.quote(self.DISPLAY)} xdpyinfo >/dev/null 2>&1",
                ],
                user="student",
            )
            if result.exit_code == 0:
                return
            time.sleep(delay_seconds)

        raise RuntimeError(
            f"X display {self.DISPLAY} did not become ready."
        )

    def _wait_until_ready(
        self,
        container_id: str,
        attempts: int = 30,
        delay_seconds: float = 0.25,
    ) -> dict:
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
        container = self._get_container(container_id)
        container.reload()

        if not container.attrs.get("State", {}).get("Running", False):
            raise RuntimeError("Lab container is not running.")

        current = self.status(container_id)

        if not current["xvfb_running"]:
            self._start_detached(
                container,
                [
                    "Xvfb",
                    self.DISPLAY,
                    "-screen",
                    "0",
                    self.SCREEN,
                    "-nolisten",
                    "tcp",
                ],
                "Starting Xvfb",
                "/tmp/wpl-xvfb.log",
            )

        if not self._process_command(container, "Xvfb"):
            self._wait_for_process(container_id, "Xvfb")

        self._wait_for_display(container_id)

        if not self._process_command(container, "fluxbox"):
            self._start_detached(
                container,
                ["fluxbox"],
                "Starting Fluxbox",
                "/tmp/wpl-fluxbox.log",
                environment={"DISPLAY": self.DISPLAY},
            )

        if not self._is_x11vnc_running(container):
            self._start_detached(
                container,
                [
                    "x11vnc",
                    "-display",
                    self.DISPLAY,
                    "-forever",
                    "-shared",
                    "-nopw",
                    "-localhost",
                    "-rfbport",
                    str(self.VNC_PORT),
                ],
                "Starting x11vnc",
                "/tmp/wpl-x11vnc.log",
            )

        if not self._is_websockify_running(container):
            self._start_detached(
                container,
                [
                    "websockify",
                    "--web",
                    self.NOVNC_WEB_ROOT,
                    str(self.WEB_PORT),
                    f"127.0.0.1:{self.VNC_PORT}",
                ],
                "Starting websockify/noVNC",
                "/tmp/wpl-websockify.log",
            )

        return self._wait_until_ready(container_id)

    def _wait_for_process(
        self,
        container_id: str,
        process_name: str,
        attempts: int = 10,
        delay_seconds: float = 0.1,
    ) -> None:
        import time

        for _ in range(attempts):
            container = self._get_container(container_id)
            if self._process_command(container, process_name):
                return
            time.sleep(delay_seconds)

        raise RuntimeError(f"{process_name} did not start.")
