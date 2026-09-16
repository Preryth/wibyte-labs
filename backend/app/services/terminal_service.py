import asyncio
import uuid
import socket

import docker


class TerminalSession:
    def __init__(self, docker_socket):
        self._socket_wrapper = docker_socket
        self.docker_socket = getattr(docker_socket, "_sock", docker_socket)
        self.docker_socket.settimeout(None)

    async def read(self):
        try:
            chunk = await asyncio.to_thread(
                self.docker_socket.recv,
                4096,
            )
            return chunk or b""
        except Exception as exc:
            print(
                f"[TerminalSession] Docker socket read error: {exc!r}",
                flush=True,
            )
            raise

    async def write(self, data: str):
        try:
            await asyncio.to_thread(
                self.docker_socket.sendall,
                data.encode("utf-8"),
            )
        except Exception as exc:
            print(
                f"[TerminalSession] Docker socket write error: {exc!r}",
                flush=True,
            )
            raise

    def close(self):
        try:
            self.docker_socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            response = getattr(self._socket_wrapper, "_response", None)
            if response is not None:
                response.close()
                self._socket_wrapper._response = None
        finally:
            try:
                self._socket_wrapper.close()
            finally:
                self.docker_socket.close()


class ProcessSession:
    """A separately managed Docker exec process used for Run/Stop."""

    def __init__(self, docker_api, exec_id: str, docker_socket, container, pid_path):
        self.docker_api = docker_api
        self.exec_id = exec_id
        self.container = container
        self.pid_path = pid_path
        self._socket_wrapper = docker_socket
        self.docker_socket = getattr(docker_socket, "_sock", docker_socket)
        self.docker_socket.settimeout(None)

    async def read(self):
        try:
            chunk = await asyncio.to_thread(
                self.docker_socket.recv,
                4096,
            )
            return chunk or b""
        except Exception as exc:
            print(
                f"[ProcessSession] Docker socket read error: {exc!r}",
                flush=True,
            )
            raise

    async def write(self, data: str):
        try:
            await asyncio.to_thread(
                self.docker_socket.sendall,
                data.encode("utf-8"),
            )
        except Exception as exc:
            print(
                f"[ProcessSession] Docker socket write error: {exc!r}",
                flush=True,
            )
            raise

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
            self.docker_socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            response = getattr(self._socket_wrapper, "_response", None)
            if response is not None:
                response.close()
                self._socket_wrapper._response = None
        finally:
            try:
                self._socket_wrapper.close()
            finally:
                self.docker_socket.close()

        try:
            self.container.exec_run(
                ["rm", "-f", "--", self.pid_path],
                user="student",
            )
        except Exception:
            pass

    async def stop(self):
        script = """
import os
import signal
import sys
import time

path = sys.argv[1]
for attempt in range(20):
    try:
        with open(path) as handle:
            pid = int(handle.read())
        break
    except (FileNotFoundError, ValueError):
        time.sleep(0.05)
else:
    raise RuntimeError("Run process PID was not available")

try:
    os.killpg(pid, signal.SIGKILL)
except ProcessLookupError:
    pass
"""
        result = await asyncio.to_thread(
            self.container.exec_run,
            ["python", "-c", script, self.pid_path],
            user="student",
        )
        if result.exit_code != 0:
            raise RuntimeError(
                result.output.decode("utf-8", errors="replace")
            )



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
            cmd=["bash", "-i"],
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
        pid_path = "/tmp/wpl-run-" + uuid.uuid4().hex + ".pid"
        container = self.docker_client.containers.get(container_id)

        exec_instance = container.client.api.exec_create(
            container.id,
            cmd=[
                "python", "-c",
                (
                    "import os,sys; "
                    "os.getpgrp() == os.getpid() or os.setsid(); "
                    "f=open(sys.argv[1], 'w'); "
                    "f.write(str(os.getpid())); f.close(); "
                    "os.execvp('bash', ['bash', '-lc', 'exec ' + sys.argv[2]])"
                ),
                pid_path,
                command,
            ],
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
            container,
            pid_path,
        )


terminal_service = None
