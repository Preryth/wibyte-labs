import io
import os
import posixpath
import shutil
import subprocess
import tarfile
import tempfile

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from uuid import uuid4

import httpx

from itsdangerous import (
    BadSignature,
    URLSafeTimedSerializer,
)

from sqlalchemy import select

from backend.app.db.database import SessionLocal
from backend.app.models.github_connection import (
    GitHubConnection,
)
from backend.app.models.github_repository import (
    GitHubRepository,
)


class GitHubService:
    """
    Handles GitHub OAuth, GitHub API communication,
    and persistent GitHub account/repository data.
    """

    GITHUB_AUTHORIZE_URL = (
        "https://github.com/login/oauth/authorize"
    )

    GITHUB_ACCESS_TOKEN_URL = (
        "https://github.com/login/oauth/access_token"
    )

    GITHUB_API_BASE_URL = (
        "https://api.github.com"
    )

    GITHUB_API_VERSION = "2026-03-10"

    def __init__(self):
        self.SessionLocal = SessionLocal

    # =========================================================
    # Configuration
    # =========================================================

    def _client_id(self) -> str:
        value = os.getenv("WPL_GITHUB_CLIENT_ID")

        if not value:
            raise RuntimeError(
                "WPL_GITHUB_CLIENT_ID environment variable "
                "is not set."
            )

        return value

    def _client_secret(self) -> str:
        value = os.getenv(
            "WPL_GITHUB_CLIENT_SECRET"
        )

        if not value:
            raise RuntimeError(
                "WPL_GITHUB_CLIENT_SECRET environment "
                "variable is not set."
            )

        return value

    def _secret_key(self) -> str:
        value = os.getenv("WPL_SECRET_KEY")

        if not value:
            raise RuntimeError(
                "WPL_SECRET_KEY environment variable "
                "is not set."
            )

        return value

    def _serializer(self) -> URLSafeTimedSerializer:
        return URLSafeTimedSerializer(
            self._secret_key(),
            salt="wpl-github-oauth",
        )

    # =========================================================
    # OAuth
    # =========================================================

    def create_oauth_state(
        self,
        student_id: str,
    ) -> str:
        """
        Create a signed OAuth state value tied
        to a WPL student.
        """

        return self._serializer().dumps(
            {
                "student_id": student_id,
            }
        )

    def verify_oauth_state(
        self,
        state: str,
        max_age_seconds: int = 600,
    ) -> str:
        """
        Verify the OAuth state and return the student ID.

        State values expire after 10 minutes.
        """

        try:
            data = self._serializer().loads(
                state,
                max_age=max_age_seconds,
            )

        except BadSignature as exc:
            raise ValueError(
                "Invalid or expired GitHub OAuth state."
            ) from exc

        student_id = data.get("student_id")

        if not student_id:
            raise ValueError(
                "GitHub OAuth state does not contain "
                "a student ID."
            )

        return student_id

    def get_authorization_url(
        self,
        student_id: str,
        redirect_uri: str,
    ) -> str:
        """
        Build the GitHub authorization URL.
        """

        state = self.create_oauth_state(student_id)

        params = {
            "client_id": self._client_id(),
            "redirect_uri": redirect_uri,
            "state": state,
            "prompt":"select_account",
        }

        return (
            f"{self.GITHUB_AUTHORIZE_URL}?"
            f"{urlencode(params)}"
        )

    def exchange_code(
        self,
        code: str,
    ) -> dict:
        """
        Exchange the GitHub OAuth authorization code
        for an access token and refresh token.
        """

        payload = {
            "client_id": self._client_id(),
            "client_secret": self._client_secret(),
            "code": code,
        }

        headers = {
            "Accept": "application/json",
        }

        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                self.GITHUB_ACCESS_TOKEN_URL,
                data=payload,
                headers=headers,
            )

        if response.status_code != 200:
            raise RuntimeError(
                "GitHub token exchange failed: "
                f"{response.status_code} {response.text}"
            )

        data = response.json()

        if "error" in data:
            raise RuntimeError(
                "GitHub token exchange failed: "
                f"{data}"
            )

        required = [
            "access_token",
            "refresh_token",
            "expires_in",
            "refresh_token_expires_in",
        ]

        missing = [
            key
            for key in required
            if key not in data
        ]

        if missing:
            raise RuntimeError(
                "GitHub token response is missing: "
                f"{', '.join(missing)}"
            )

        return data

    def get_authenticated_user(
        self,
        access_token: str,
    ) -> dict:
        """
        Retrieve the GitHub user associated
        with an access token.
        """

        headers = self._api_headers(
            access_token
        )

        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{self.GITHUB_API_BASE_URL}/user",
                headers=headers,
            )

        if response.status_code != 200:
            raise RuntimeError(
                "GitHub user lookup failed: "
                f"{response.status_code} {response.text}"
            )

        return response.json()

    def connect_from_oauth(
        self,
        student_id: str,
        code: str,
    ) -> GitHubConnection:
        """
        Complete the OAuth flow and persist
        the GitHub connection.
        """

        token_data = self.exchange_code(code)

        access_token = token_data["access_token"]
        refresh_token = token_data["refresh_token"]

        expires_in = int(
            token_data["expires_in"]
        )

        refresh_token_expires_in = int(
            token_data["refresh_token_expires_in"]
        )

        now = datetime.now(timezone.utc)

        access_token_expires_at = (
            now
            + timedelta(
                seconds=expires_in
            )
        )

        refresh_token_expires_at = (
            now
            + timedelta(
                seconds=refresh_token_expires_in
            )
        )

        github_user = self.get_authenticated_user(
            access_token
        )

        github_user_id = str(
            github_user["id"]
        )

        github_username = github_user["login"]

        return self.save_connection(
            student_id=student_id,
            github_user_id=github_user_id,
            github_username=github_username,
            access_token=access_token,
            refresh_token=refresh_token,
            access_token_expires_at=(
                access_token_expires_at
            ),
            refresh_token_expires_at=(
                refresh_token_expires_at
            ),
        )

    # =========================================================
    # Token management
    # =========================================================

    def refresh_access_token(
        self,
        connection: GitHubConnection,
    ) -> GitHubConnection:
        """
        Refresh an expired GitHub access token.

        GitHub rotates the refresh token when
        the refresh succeeds.
        """

        if not connection.refresh_token:
            raise RuntimeError(
                "GitHub connection has no refresh token."
            )

        payload = {
            "client_id": self._client_id(),
            "client_secret": self._client_secret(),
            "grant_type": "refresh_token",
            "refresh_token": (
                connection.refresh_token
            ),
        }

        headers = {
            "Accept": "application/json",
        }

        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                self.GITHUB_ACCESS_TOKEN_URL,
                data=payload,
                headers=headers,
            )

        if response.status_code != 200:
            raise RuntimeError(
                "GitHub token refresh failed: "
                f"{response.status_code} {response.text}"
            )

        data = response.json()

        if "error" in data:
            raise RuntimeError(
                "GitHub token refresh failed: "
                f"{data}"
            )

        now = datetime.now(timezone.utc)

        connection.access_token = (
            data["access_token"]
        )

        connection.refresh_token = (
            data["refresh_token"]
        )

        connection.access_token_expires_at = (
            now
            + timedelta(
                seconds=int(
                    data["expires_in"]
                )
            )
        )

        connection.refresh_token_expires_at = (
            now
            + timedelta(
                seconds=int(
                    data["refresh_token_expires_in"]
                )
            )
        )

        connection.updated_at = now

        db = self.SessionLocal()

        try:
            db.merge(connection)
            db.commit()

            db.refresh(connection)

            return connection

        finally:
            db.close()

    def _get_valid_connection(
        self,
        student_id: str,
    ) -> GitHubConnection:
        """
        Get the student's GitHub connection and refresh
        its access token when it is expired or about
        to expire.
        """

        connection = self.get_connection(
            student_id
        )

        if connection is None:
            raise RuntimeError(
                "GitHub account is not connected."
            )

        now = datetime.now(timezone.utc)

        expires_at = (
            connection.access_token_expires_at
        )

        if expires_at is not None:

            # SQLite may return DateTime values without
            # timezone information. Treat naive database
            # timestamps as UTC before comparing them with
            # the timezone-aware current time.
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(
                    tzinfo=timezone.utc
                )

            # Refresh one minute before expiration.
            if expires_at <= (
                now + timedelta(minutes=1)
            ):
                connection = (
                    self.refresh_access_token(
                        connection
                    )
                )

        return connection

    def _api_headers(
        self,
        access_token: str,
    ) -> dict:
        return {
            "Accept": (
                "application/vnd.github+json"
            ),
            "Authorization": (
                f"Bearer {access_token}"
            ),
            "X-GitHub-Api-Version": (
                self.GITHUB_API_VERSION
            ),
        }

    # =========================================================
    # Persistent GitHub connection
    # =========================================================

    def get_connection(
        self,
        student_id: str,
    ) -> GitHubConnection | None:

        db = self.SessionLocal()

        try:
            connection = (
                db.execute(
                    select(GitHubConnection)
                    .where(
                        GitHubConnection.student_id
                        == student_id
                    )
                )
                .scalars()
                .first()
            )

            return connection

        finally:
            db.close()

    def save_connection(
        self,
        student_id: str,
        github_user_id: str,
        github_username: str,
        access_token: str,
        refresh_token: str,
        access_token_expires_at: datetime,
        refresh_token_expires_at: datetime,
    ) -> GitHubConnection:

        db = self.SessionLocal()

        try:
            connection = (
                db.execute(
                    select(GitHubConnection)
                    .where(
                        GitHubConnection.student_id
                        == student_id
                    )
                )
                .scalars()
                .first()
            )

            now = datetime.now(timezone.utc)

            if connection is None:

                connection = GitHubConnection(
                    id=str(uuid4()),
                    student_id=student_id,
                    github_user_id=(
                        github_user_id
                    ),
                    github_username=(
                        github_username
                    ),
                    access_token=access_token,
                    refresh_token=refresh_token,
                    access_token_expires_at=(
                        access_token_expires_at
                    ),
                    refresh_token_expires_at=(
                        refresh_token_expires_at
                    ),
                    connected_at=now,
                    updated_at=now,
                )

                db.add(connection)

            else:

                connection.github_user_id = (
                    github_user_id
                )

                connection.github_username = (
                    github_username
                )

                connection.access_token = (
                    access_token
                )

                connection.refresh_token = (
                    refresh_token
                )

                connection.access_token_expires_at = (
                    access_token_expires_at
                )

                connection.refresh_token_expires_at = (
                    refresh_token_expires_at
                )

                connection.updated_at = now

            db.commit()
            db.refresh(connection)

            return connection

        finally:
            db.close()

    def delete_connection(
        self,
        student_id: str,
    ) -> bool:

        db = self.SessionLocal()

        try:
            connection = (
                db.execute(
                    select(GitHubConnection)
                    .where(
                        GitHubConnection.student_id
                        == student_id
                    )
                )
                .scalars()
                .first()
            )

            if connection is None:
                return False

            db.delete(connection)
            db.commit()

            return True

        finally:
            db.close()

    # =========================================================
    # GitHub repository API
    # =========================================================

    def fetch_github_repositories(
        self,
        student_id: str,
    ) -> list[dict]:
        """
        Fetch repositories accessible to the student's
        connected GitHub account.

        The repositories are returned from GitHub and
        are also synchronized into the local database.
        """

        connection = (
            self._get_valid_connection(
                student_id
            )
        )

        headers = self._api_headers(
            connection.access_token
        )

        repositories: list[dict] = []

        page = 1

        with httpx.Client(timeout=20.0) as client:

            while True:

                response = client.get(
                    f"{self.GITHUB_API_BASE_URL}/user/repos",
                    headers=headers,
                    params={
                        "visibility": "all",
                        "affiliation": (
                            "owner,"
                            "collaborator,"
                            "organization_member"
                        ),
                        "sort": "updated",
                        "direction": "desc",
                        "per_page": 100,
                        "page": page,
                    },
                )

                if response.status_code == 401:
                    raise RuntimeError(
                        "GitHub access token was rejected."
                    )

                if response.status_code != 200:
                    raise RuntimeError(
                        "GitHub repository lookup failed: "
                        f"{response.status_code} "
                        f"{response.text}"
                    )

                batch = response.json()

                if not batch:
                    break

                for repository in batch:

                    saved = self.save_repository(
                        student_id=student_id,
                        github_repo_id=str(
                            repository["id"]
                        ),
                        owner=(
                            repository["owner"]["login"]
                        ),
                        name=repository["name"],
                        full_name=(
                            repository["full_name"]
                        ),
                        default_branch=(
                            repository.get(
                                "default_branch"
                            )
                            or "main"
                        ),
                    )

                    repositories.append(
                        {
                            "id": saved.id,
                            "github_repo_id": (
                                saved.github_repo_id
                            ),
                            "owner": saved.owner,
                            "name": saved.name,
                            "full_name": (
                                saved.full_name
                            ),
                            "default_branch": (
                                saved.default_branch
                            ),
                            "private": bool(
                                repository.get(
                                    "private",
                                    False,
                                )
                            ),
                            "html_url": (
                                repository.get(
                                    "html_url"
                                )
                            ),
                            "description": (
                                repository.get(
                                    "description"
                                )
                            ),
                        }
                    )

                if len(batch) < 100:
                    break

                page += 1

        return repositories

    # =========================================================
    # Local repository persistence
    # =========================================================

    def get_repositories(
        self,
        student_id: str,
    ) -> list[GitHubRepository]:

        db = self.SessionLocal()

        try:
            repositories = (
                db.execute(
                    select(GitHubRepository)
                    .where(
                        GitHubRepository.student_id
                        == student_id
                    )
                    .order_by(
                        GitHubRepository.name
                    )
                )
                .scalars()
                .all()
            )

            return repositories

        finally:
            db.close()

    def get_repository(
        self,
        repository_id: str,
    ) -> GitHubRepository | None:

        db = self.SessionLocal()

        try:
            return db.get(
                GitHubRepository,
                repository_id,
            )

        finally:
            db.close()

    def save_repository(
        self,
        student_id: str,
        github_repo_id: str,
        owner: str,
        name: str,
        full_name: str,
        default_branch: str,
    ) -> GitHubRepository:

        db = self.SessionLocal()

        try:
            repository = (
                db.execute(
                    select(GitHubRepository)
                    .where(
                        GitHubRepository.student_id
                        == student_id,
                        GitHubRepository.github_repo_id
                        == github_repo_id,
                    )
                )
                .scalars()
                .first()
            )

            now = datetime.now(timezone.utc)

            if repository is None:

                repository = GitHubRepository(
                    id=str(uuid4()),
                    student_id=student_id,
                    github_repo_id=(
                        github_repo_id
                    ),
                    owner=owner,
                    name=name,
                    full_name=full_name,
                    default_branch=(
                        default_branch
                    ),
                    created_at=now,
                    updated_at=now,
                )

                db.add(repository)

            else:

                repository.owner = owner
                repository.name = name
                repository.full_name = (
                    full_name
                )
                repository.default_branch = (
                    default_branch
                )
                repository.updated_at = now

            db.commit()
            db.refresh(repository)

            return repository

        finally:
            db.close()

    # =========================================================
    # Repository provisioning into Docker lab
    # =========================================================

    def provision_repository(
        self,
        student_id: str,
        repository_id: str,
        container_id: str,
    ) -> dict:
        """
        Provision the selected GitHub repository into the lab container.

        A temporary real Git clone is created on the WPL backend host using
        the student's OAuth access token through Git's credential helper.
        The token is never written into the repository remote URL and is
        never passed into the Docker container.

        The cloned repository, including its .git directory, is then
        copied into /workspace as a sanitized tar archive. The temporary
        clone and its credentials are removed when provisioning finishes.
        """

        connection = self._get_valid_connection(student_id)

        repository = self.get_repository(repository_id)

        if repository is None:
            raise ValueError(
                "GitHub repository not found."
            )

        if repository.student_id != student_id:
            raise ValueError(
                "GitHub repository does not belong to this student."
            )

        if not connection.access_token:
            raise RuntimeError(
                "GitHub connection does not contain an access token."
            )

        import docker

        try:
            docker_client = docker.from_env()

            try:
                container = docker_client.containers.get(
                    container_id
                )
            except docker.errors.NotFound as exc:
                raise ValueError(
                    "Lab container not found."
                ) from exc

            # Create the temporary clone outside the Docker container.
            # The OAuth token is supplied to Git through an in-memory
            # environment variable and a temporary credential helper.
            with tempfile.TemporaryDirectory(
                prefix="wpl-git-"
            ) as temp_dir:

                clone_dir = os.path.join(
                    temp_dir,
                    "repository",
                )

                repository_url = (
                    f"https://github.com/"
                    f"{repository.owner}/"
                    f"{repository.name}.git"
                )

                env = os.environ.copy()
                env["WPL_GITHUB_TOKEN"] = (
                    connection.access_token
                )
                env["GIT_TERMINAL_PROMPT"] = "0"

                # Git for Windows executes credential helpers through its
                # shell. The token is supplied through the environment rather
                # than being placed in the clone URL or command arguments.
                credential_helper = (
                    "!f() { "
                    "echo username=x-access-token; "
                    "echo password=$WPL_GITHUB_TOKEN; "
                    "}; f"
                )

                command = [
                    "git",
                    "-c",
                    "credential.helper=" + credential_helper,
                    "-c",
                    "credential.useHttpPath=false",
                    "clone",
                    "--branch",
                    repository.default_branch,
                    repository_url,
                    clone_dir,
                ]

                result = subprocess.run(
                    command,
                    cwd=temp_dir,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=300,
                    check=False,
                )

                if result.returncode != 0:
                    detail = (
                        result.stderr.strip()
                        or result.stdout.strip()
                        or "unknown Git error"
                    )

                    # Do not expose the OAuth token in an error message.
                    detail = detail.replace(
                        connection.access_token,
                        "[REDACTED]",
                    )

                    raise RuntimeError(
                        "GitHub repository clone failed: "
                        f"{detail}"
                    )

                git_dir = os.path.join(
                    clone_dir,
                    ".git",
                )

                if not os.path.isdir(git_dir):
                    raise RuntimeError(
                        "Git clone completed but the cloned "
                        "repository does not contain a .git directory."
                    )

                # Build a sanitized tar archive for Docker. The repository's
                # .git directory is intentionally included. Symlinks are
                # skipped so a repository cannot introduce a symlink that
                # escapes /workspace when the archive is extracted.
                sanitized = io.BytesIO()

                files_loaded = 0

                with tarfile.open(
                    fileobj=sanitized,
                    mode="w",
                ) as output:

                    for root, dirs, files in os.walk(
                        clone_dir,
                        topdown=True,
                        followlinks=False,
                    ):
                        # Never descend through symlinked directories.
                        dirs[:] = [
                            name
                            for name in dirs
                            if not os.path.islink(
                                os.path.join(root, name)
                            )
                        ]

                        relative_root = os.path.relpath(
                            root,
                            clone_dir,
                        )

                        if relative_root != ".":
                            output.add(
                                root,
                                arcname=relative_root,
                                recursive=False,
                            )

                        for name in files:
                            source_path = os.path.join(
                                root,
                                name,
                            )

                            # Skip symlinked files for the same safety reason.
                            if os.path.islink(source_path):
                                continue

                            relative_path = os.path.relpath(
                                source_path,
                                clone_dir,
                            )

                            normalized = posixpath.normpath(
                                relative_path.replace(
                                    os.sep,
                                    "/",
                                )
                            )

                            if (
                                normalized.startswith("../")
                                or normalized == ".."
                                or normalized.startswith("/")
                            ):
                                raise RuntimeError(
                                    "Cloned repository contains an "
                                    "invalid path."
                                )

                            output.add(
                                source_path,
                                arcname=normalized,
                                recursive=False,
                            )

                            files_loaded += 1

                sanitized.seek(0)

                result = container.put_archive(
                    "/workspace",
                    sanitized.getvalue(),
                )

                if not result:
                    raise RuntimeError(
                        "Failed to copy repository into the lab workspace."
                    )

                # Docker's put_archive writes files as root. The lab itself
                # runs as the unprivileged "student" user, so hand ownership
                # of the entire workspace to that user before returning.
                chown_result = container.exec_run(
                    [
                        "chown",
                        "-R",
                        "student:student",
                        "/workspace",
                    ],
                    user="root",
                )

                if chown_result.exit_code != 0:
                    detail = chown_result.output.decode(
                        "utf-8",
                        errors="replace",
                    ).strip()

                    raise RuntimeError(
                        "Failed to assign workspace ownership to "
                        f"the student user: {detail}"
                    )

                return {
                    "repository_id": repository.id,
                    "github_repo_id": repository.github_repo_id,
                    "full_name": repository.full_name,
                    "default_branch": repository.default_branch,
                    "files_loaded": files_loaded,
                    "git_repository": True,
                }

        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                "GitHub repository clone timed out."
            ) from exc
        finally:
            # The TemporaryDirectory context removes the cloned repository
            # and any temporary Git metadata/credential material.
            pass

    def delete_repository(
        self,
        repository_id: str,
    ) -> bool:

        db = self.SessionLocal()

        try:
            repository = db.get(
                GitHubRepository,
                repository_id,
            )

            if repository is None:
                return False

            db.delete(repository)
            db.commit()

            return True

        finally:
            db.close()


github_service = GitHubService()