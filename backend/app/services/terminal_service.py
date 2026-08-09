import asyncio

import docker


class TerminalSession:
    def __init__(self, docker_socket):
        self.docker_socket = docker_socket

    async def read(self):
        return await asyncio.to_thread(
            self.docker_socket.recv,
            4096,
        )

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