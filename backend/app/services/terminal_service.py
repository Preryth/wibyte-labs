import asyncio
import struct

import docker


class TerminalSession:
    def __init__(self, docker_socket):
        self.docker_socket = docker_socket
        self._buffer = b""

    async def read(self):
        while True:
            if len(self._buffer) >= 8:
                stream_type = self._buffer[0]
                data_size = struct.unpack(
                    ">I",
                    self._buffer[4:8],
                )[0]

                if len(self._buffer) >= 8 + data_size:
                    data = self._buffer[8:8 + data_size]
                    self._buffer = self._buffer[8 + data_size:]

                    return data

            try:
                chunk = await asyncio.to_thread(
                    self.docker_socket.recv,
                    4096,
                )
            except Exception:
                return b""

            if not chunk:
                return b""

            self._buffer += chunk

    async def write(self, data: str):
        await asyncio.to_thread(
            self.docker_socket.send,
            data.encode("utf-8"),
        )

    def close(self):
        try:
            self.docker_socket.close()
        except Exception:
            pass


class TerminalService:
    def __init__(self, docker_client: docker.DockerClient):
        self.docker_client = docker_client

    def create_session(self, container_id: str) -> TerminalSession:
        container = self.docker_client.containers.get(container_id)

        exec_instance = container.client.api.exec_create(
            container.id,
            cmd=["bash"],
            stdin=True,
            stdout=True,
            stderr=True,
            tty=True,
        )

        docker_socket = container.client.api.exec_start(
            exec_instance["Id"],
            socket=True,
        )

        return TerminalSession(docker_socket)


terminal_service = None