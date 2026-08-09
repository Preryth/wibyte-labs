import posixpath
import shlex

import docker


class WorkspaceService:
    WORKSPACE_ROOT = "/workspace"

    def __init__(self, docker_client: docker.DockerClient):
        self.docker_client = docker_client

    def _get_container(self, container_id: str):
        return self.docker_client.containers.get(container_id)

    def _safe_path(self, path: str) -> str:
        path = path.strip()

        if not path:
            raise ValueError("Path cannot be empty")

        if path.startswith("/"):
            relative_path = path.lstrip("/")
        else:
            relative_path = path

        normalized = posixpath.normpath(relative_path)

        if normalized == ".." or normalized.startswith("../"):
            raise ValueError("Path escapes workspace")

        return posixpath.join(
            self.WORKSPACE_ROOT,
            normalized,
        )

    def list_files(
        self,
        container_id: str,
        path: str = ".",
    ):
        container = self._get_container(container_id)
        workspace_path = self._safe_path(path)

        result = container.exec_run(
            [
                "bash",
                "-lc",
                (
                    f"find {shlex.quote(workspace_path)} "
                    "-maxdepth 1 "
                    "-mindepth 1 "
                    "-printf '%y\\t%f\\n' | sort"
                ),
            ]
        )

        if result.exit_code != 0:
            raise FileNotFoundError(path)

        files = []

        for line in result.output.decode(
            "utf-8",
            errors="replace",
        ).splitlines():
            if not line:
                continue

            file_type, name = line.split(
                "\t",
                1,
            )

            files.append(
                {
                    "name": name,
                    "type": (
                        "directory"
                        if file_type == "d"
                        else "file"
                    ),
                }
            )

        return files

    def read_file(
        self,
        container_id: str,
        path: str,
    ):
        container = self._get_container(container_id)
        file_path = self._safe_path(path)

        result = container.exec_run(
            [
                "bash",
                "-lc",
                f"cat -- {shlex.quote(file_path)}",
            ]
        )

        if result.exit_code != 0:
            raise FileNotFoundError(path)

        return result.output.decode(
            "utf-8",
            errors="replace",
        )

    def write_file(
        self,
        container_id: str,
        path: str,
        content: str,
    ):
        container = self._get_container(container_id)
        file_path = self._safe_path(path)

        encoded_content = content.encode(
            "utf-8"
        ).hex()

        result = container.exec_run(
            [
                "python",
                "-c",
                (
                    "from pathlib import Path; "
                    f"path = Path({file_path!r}); "
                    "path.parent.mkdir("
                    "parents=True, "
                    "exist_ok=True"
                    "); "
                    f"path.write_bytes("
                    f"bytes.fromhex("
                    f"{encoded_content!r}"
                    ")"
                    ")"
                ),
            ]
        )

        if result.exit_code != 0:
            raise RuntimeError(
                "Failed to write file: "
                + result.output.decode(
                    "utf-8",
                    errors="replace",
                )
            )

    def create_file(
        self,
        container_id: str,
        path: str,
    ):
        container = self._get_container(container_id)
        file_path = self._safe_path(path)

        result = container.exec_run(
            [
                "bash",
                "-lc",
                (
                    f"mkdir -p -- "
                    f"$(dirname -- "
                    f"{shlex.quote(file_path)}"
                    f") && "
                    f"touch -- "
                    f"{shlex.quote(file_path)}"
                ),
            ]
        )

        if result.exit_code != 0:
            raise RuntimeError(
                "Failed to create file"
            )

    def create_directory(
        self,
        container_id: str,
        path: str,
    ):
        container = self._get_container(container_id)
        directory_path = self._safe_path(path)

        result = container.exec_run(
            [
                "bash",
                "-lc",
                (
                    f"mkdir -p -- "
                    f"{shlex.quote(directory_path)}"
                ),
            ]
        )

        if result.exit_code != 0:
            raise RuntimeError(
                "Failed to create directory"
            )

    def delete(
        self,
        container_id: str,
        path: str,
    ):
        container = self._get_container(container_id)
        target_path = self._safe_path(path)

        if target_path == self.WORKSPACE_ROOT:
            raise ValueError(
                "Cannot delete workspace root"
            )

        result = container.exec_run(
            [
                "bash",
                "-lc",
                (
                    f"rm -rf -- "
                    f"{shlex.quote(target_path)}"
                ),
            ]
        )

        if result.exit_code != 0:
            raise RuntimeError(
                "Failed to delete path"
            )

    def rename(
        self,
        container_id: str,
        old_path: str,
        new_path: str,
    ):
        container = self._get_container(
            container_id
        )

        source_path = self._safe_path(
            old_path
        )

        destination_path = self._safe_path(
            new_path
        )

        if (
            source_path
            == self.WORKSPACE_ROOT
        ):
            raise ValueError(
                "Cannot rename workspace root"
            )

        if (
            destination_path
            == self.WORKSPACE_ROOT
        ):
            raise ValueError(
                "Cannot rename to workspace root"
            )

        if source_path == destination_path:
            raise ValueError(
                "New path is the same as the old path"
            )

        source_quoted = shlex.quote(
            source_path
        )

        destination_quoted = shlex.quote(
            destination_path
        )

        result = container.exec_run(
            [
                "bash",
                "-lc",
                (
                    # Source must exist.
                    f"if [ ! -e {source_quoted} ]; "
                    "then "
                    "exit 10; "
                    "fi; "

                    # Destination must not already exist.
                    f"if [ -e {destination_quoted} ]; "
                    "then "
                    "exit 11; "
                    "fi; "

                    # Create destination parent directory.
                    f"mkdir -p -- "
                    f"$(dirname -- "
                    f"{destination_quoted}"
                    f") || exit 12; "

                    # Move the file/directory.
                    f"mv -- "
                    f"{source_quoted} "
                    f"{destination_quoted}"
                ),
            ]
        )

        if result.exit_code == 10:
            raise FileNotFoundError(
                old_path
            )

        if result.exit_code == 11:
            raise FileExistsError(
                new_path
            )

        if result.exit_code != 0:
            raise RuntimeError(
                "Failed to rename path: "
                + result.output.decode(
                    "utf-8",
                    errors="replace",
                )
            )