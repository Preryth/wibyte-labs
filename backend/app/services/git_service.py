from __future__ import annotations

import re

import docker

from sqlalchemy import select

from backend.app.db.database import SessionLocal
from backend.app.models.github_repository import GitHubRepository
from backend.app.models.lab_db import Lab
from backend.app.models.student import Student
from backend.app.services.github_service import github_service


class GitService:
    """Git operations for the repository already provisioned into a Lab."""

    WORKSPACE = "/workspace/wibyte-workspace"

    def __init__(self, docker_client: docker.DockerClient):
        self.docker_client = docker_client
        self.SessionLocal = SessionLocal

    def _lab_and_student(self, lab_id: str) -> tuple[Lab, Student, GitHubRepository]:
        db = self.SessionLocal()
        try:
            lab = db.get(Lab, lab_id)
            if lab is None:
                raise ValueError("Lab not found.")
            if lab.github_repository_id is None:
                raise ValueError("This Lab is not connected to a GitHub repository.")

            student = db.get(Student, lab.student_id)
            if student is None:
                raise ValueError("Lab student not found.")

            repository = db.get(GitHubRepository, lab.github_repository_id)
            if repository is None:
                raise ValueError("GitHub repository not found.")
            if repository.student_id != student.id:
                raise ValueError("GitHub repository does not belong to this student.")

            # Detach values from the DB session before it closes.
            db.expunge(lab)
            db.expunge(student)
            db.expunge(repository)
            return lab, student, repository
        finally:
            db.close()

    def _container(self, container_id: str):
        try:
            return self.docker_client.containers.get(container_id)
        except docker.errors.NotFound as exc:
            raise ValueError("Lab container not found.") from exc

    def _run(self, container_id: str, command: list[str], *, environment: dict[str, str] | None = None):
        container = self._container(container_id)
        result = container.exec_run(command, workdir=self.WORKSPACE, environment=environment)
        output = result.output.decode("utf-8", errors="replace").strip()
        if result.exit_code != 0:
            raise RuntimeError(output or "Git command failed.")
        return output

    def _assert_repository(self, lab_id: str):
        lab, student, repository = self._lab_and_student(lab_id)
        self._run(lab.container_id, ["git", "rev-parse", "--is-inside-work-tree"])
        return lab, student, repository

    @staticmethod
    def _parse_branch(line: str) -> tuple[str | None, int, int]:
        if not line.startswith("## "):
            return None, 0, 0
        value = line[3:]
        branch = value.split("...", 1)[0].strip() or None
        ahead = 0
        behind = 0
        match = re.search(r"\[([^\]]+)\]", value)
        if match:
            for part in match.group(1).split(","):
                part = part.strip()
                if part.startswith("ahead "):
                    try: ahead = int(part.split()[1])
                    except (IndexError, ValueError): pass
                elif part.startswith("behind "):
                    try: behind = int(part.split()[1])
                    except (IndexError, ValueError): pass
        return branch, ahead, behind

    def status(self, lab_id: str) -> dict:
        lab, _student, _repository = self._assert_repository(lab_id)
        output = self._run(lab.container_id, ["git", "status", "--porcelain=v1", "--branch"])
        lines = output.splitlines() if output else []
        branch, ahead, behind = self._parse_branch(lines[0]) if lines else (None, 0, 0)
        changes = []
        for line in lines[1:]:
            if len(line) < 3:
                continue
            changes.append({"index": line[0], "worktree": line[1], "path": line[3:]})
        return {"lab_id": lab_id, "branch": branch, "ahead": ahead, "behind": behind, "clean": not changes, "changes": changes}

    def diff(self, lab_id: str, path: str | None = None) -> dict:
        lab, _student, _repository = self._assert_repository(lab_id)
        command = ["git", "diff", "--no-ext-diff"]
        staged_command = ["git", "diff", "--no-ext-diff", "--cached"]
        if path:
            command += ["--", path]
            staged_command += ["--", path]
        return {
            "lab_id": lab_id,
            "path": path,
            "unstaged": self._run(lab.container_id, command),
            "staged": self._run(lab.container_id, staged_command),
        }

    def commit(self, lab_id: str, message: str) -> dict:
        message = message.strip()
        if not message:
            raise ValueError("Commit message cannot be empty.")
        lab, student, _repository = self._assert_repository(lab_id)
        self._run(lab.container_id, ["git", "add", "-A"])
        status = self.status(lab_id)
        if status["clean"]:
            raise ValueError("There are no changes to commit.")

        connection = github_service._get_valid_connection(student.id)
        name = (student.name or connection.github_username or "Wibyte Labs Student").strip()
        email = (student.email or f"{connection.github_username}@users.noreply.github.com").strip()
        output = self._run(lab.container_id, [
            "git", "-c", f"user.name={name}", "-c", f"user.email={email}",
            "commit", "-m", message,
        ])
        return {"lab_id": lab_id, "message": message, "output": output, "status": self.status(lab_id)}

    def _remote_environment(self, student_id: str) -> dict[str, str]:
        connection = github_service._get_valid_connection(student_id)
        if not connection.access_token:
            raise RuntimeError("GitHub connection does not contain an access token.")
        return {"WPL_GITHUB_TOKEN": connection.access_token, "GIT_TERMINAL_PROMPT": "0"}

    @staticmethod
    def _credential_command(args: list[str]) -> list[str]:
        helper = "!f() { echo username=x-access-token; echo password=$WPL_GITHUB_TOKEN; }; f"
        return ["git", "-c", f"credential.helper={helper}", "-c", "credential.useHttpPath=false", *args]

    def push(self, lab_id: str) -> dict:
        lab, student, _repository = self._assert_repository(lab_id)
        branch = self._run(lab.container_id, ["git", "branch", "--show-current"])
        if not branch:
            raise ValueError("Cannot push from a detached HEAD.")
        output = self._run(lab.container_id, self._credential_command(["push", "origin", f"HEAD:refs/heads/{branch}"]), environment=self._remote_environment(student.id))
        return {"lab_id": lab_id, "branch": branch, "output": output, "status": self.status(lab_id)}

    def pull(self, lab_id: str) -> dict:
        lab, student, _repository = self._assert_repository(lab_id)
        branch = self._run(lab.container_id, ["git", "branch", "--show-current"])
        if not branch:
            raise ValueError("Cannot pull into a detached HEAD.")
        output = self._run(lab.container_id, self._credential_command(["pull", "--ff-only", "origin", branch]), environment=self._remote_environment(student.id))
        return {"lab_id": lab_id, "branch": branch, "output": output, "status": self.status(lab_id)}
