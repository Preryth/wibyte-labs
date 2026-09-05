import asyncio

import docker


class TerminalSession:
    def __init__(self, docker_socket):
        self.docker_socket = docker_socket

    async def read(self):
        try:
            chunk = await asyncio.to_thread(
                self.docker_socket.read,
                4096,
            )
            return chunk or b""
        except Exception as exc:
            print(f"[ProcessSession] Docker socket read error: {exc!r}", flush=True)
            raise
    async def write(self, data: str):
        try:
            await asyncio.to_thread(
                self.docker_socket.send,
                data.encode("utf-8"),
            )
        except Exception:
            pass

    def close(self):
        try:
            self.docker_socket.close()
        except Exception:
            pass


class ProcessSession:
    """A separately managed Docker exec process used for Run/Stop."""

    def __init__(self, docker_api, exec_id: str, docker_socket):
        self.docker_api = docker_api
        self.exec_id = exec_id
        self.docker_socket = docker_socket

    async def read(self):
        try:
            chunk = await asyncio.to_thread(
                self.docker_socket.read,
                4096,
            )
        except Exception:
            return b""

        return chunk or b""

    async def write(self, data: str):
        try:
            await asyncio.to_thread(
                self.docker_socket.send,
                data.encode("utf-8"),
            )
        except Exception:
            pass

    def is_running(self) -> bool:
        try:
            result = self.docker_api.exec_inspect(self.exec_id)
            return bool(result.get("Running", False))
        except Exception:
            return False

    def exit_code(self) -> int:
        try:
            result = self.docker_api.exec_inspect(self.exec_id)
            code = result.get("ExitCode")
            return int(code) if code is not None else -1
        except Exception:
            return -1

    def close(self):
        try:
            self.docker_socket.close()
        except Exception:
            pass


class TerminalService:
    def __init__(
        self,
        docker_client: docker.DockerClient,
    ):
        self.docker_client = docker_client

    def create_session(
        self,
        container_id: str,
    ) -> TerminalSession:
        container = self.docker_client.containers.get(container_id)

        exec_instance = container.client.api.exec_create(
            container.id,
            cmd=["bash"],
            stdin=True,
            stdout=True,
            stderr=True,
            tty=True,
            user="student",
            workdir="/workspace/wibyte-workspace",
        )

        docker_socket = container.client.api.exec_start(
            exec_instance["Id"],
            socket=True,
            tty=True,
        )

        return TerminalSession(docker_socket)

    def start_process(
        self,
        container_id: str,
        command: str,
        environment: dict[str, str] | None = None,
    ) -> ProcessSession:
        container = self.docker_client.containers.get(container_id)

        exec_instance = container.client.api.exec_create(
            container.id,
            cmd=["bash", "-lc", command],
            stdin=True,
            stdout=True,
            stderr=True,
            tty=True,
            user="student",
            workdir="/workspace/wibyte-workspace",
            environment=environment,
        )

        docker_socket = container.client.api.exec_start(
            exec_instance["Id"],
            socket=True,
            tty=True,
        )

        return ProcessSession(
            container.client.api,
            exec_instance["Id"],
            docker_socket,
        )


terminal_service = None
