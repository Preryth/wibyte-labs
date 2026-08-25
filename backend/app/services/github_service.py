import io
import os
import posixpath
import shutil
import shlex
import subprocess
import tarfile
import tempfile

from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode
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
from backend.app.models.student import Student


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
            "prompt": "select_account",
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

            github_connection = (
                db.execute(
                    select(GitHubConnection)
                    .where(
                        GitHubConnection.github_user_id
                        == github_user_id
                    )
                )
                .scalars()
                .first()
            )

            if (
                github_connection is not None
                and github_connection.student_id != student_id
            ):
                # A GitHub account must not normally be shared between
                # different WiByte accounts. The only exception we support
                # is migrating a connection created by the old local
                # development setup, whose student record has no identity
                # information. This preserves existing development data
                # without allowing one real user to take another user's
                # GitHub connection.
                legacy_student = db.get(
                    Student,
                    github_connection.student_id,
                )

                if legacy_student is None:
                    raise RuntimeError(
                        "This GitHub account is already connected to "
                        "another WiByte Labs account."
                    )

                current_student = db.get(
                    Student,
                    student_id,
                )

                legacy_email = (
                    legacy_student.email or ""
                ).strip().lower()

                current_email = (
                    (current_student.email if current_student else None)
                    or ""
                ).strip().lower()

                # Connections created before Supabase authentication may
                # belong to an older local student record. We can safely
                # migrate those records when they have no identity details,
                # or when the old and current records clearly represent the
                # same email address. A connection belonging to a different
                # identified account must remain protected.
                is_legacy_connection = (
                    not legacy_email
                    or (
                        current_email
                        and legacy_email == current_email
                    )
                )

                if not is_legacy_connection:
                    raise RuntimeError(
                        "This GitHub account is already connected to "
                        "another WiByte Labs account."
                    )

                if connection is not None:
                    raise RuntimeError(
                        "A GitHub connection is already active for this "
                        "WiByte Labs account."
                    )

                github_connection.student_id = student_id
                connection = github_connection

                # Repository records created by the legacy development
                # account belong to the same GitHub identity, so migrate
                # them with the connection.
                db.query(GitHubRepository).filter(
                    GitHubRepository.student_id
                    == legacy_student.id
                ).update(
                    {"student_id": student_id},
                    synchronize_session=False,
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
        copied into /workspace/wibyte-workspace as a sanitized tar archive. The temporary
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

            # The permanent repository always lives inside its own
            # directory. The Lab setup creates /workspace/wibyte-workspace
            # before provisioning, so /workspace itself is expected to be
            # non-empty. Only the repository directory must be empty before
            # we copy a fresh clone into it.
            workspace_root = "/workspace/wibyte-workspace"

            workspace_check = container.exec_run(
                [
                    "bash",
                    "-lc",
                    (
                        f"mkdir -p -- {shlex.quote(workspace_root)} "
                        "&& find "
                        f"{shlex.quote(workspace_root)} "
                        "-mindepth 1 -maxdepth 1 -print -quit"
                    ),
                ],
                user="student",
            )

            if workspace_check.exit_code != 0:
                raise RuntimeError(
                    "Failed to inspect the Lab workspace."
                )

            if workspace_check.output.strip():
                raise ValueError(
                    "The Lab repository workspace is not empty. "
                    "Refusing to replace its files."
                )

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

                mkdir_result = container.exec_run(
                    ["mkdir", "-p", "/workspace/wibyte-workspace"],
                    user="root",
                )
                if mkdir_result.exit_code != 0:
                    raise RuntimeError("Failed to create the Lab workspace directory.")

                result = container.put_archive(
                    "/workspace/wibyte-workspace",
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

    def fetch_repository_contents(
        self,
        student_id: str,
        repository_id: str,
        path: str = "",
    ) -> list[dict]:
        """
        Return the contents of a GitHub repository directory.

        This is read-only repository browsing for the Lab file
        explorer. It does not copy files into the Docker workspace.
        """
        connection = self._get_valid_connection(student_id)
        repository = self.get_repository(repository_id)

        if repository is None:
            raise ValueError("GitHub repository not found.")

        if repository.student_id != student_id:
            raise ValueError(
                "GitHub repository does not belong to this student."
            )

        clean_path = path.strip().strip("/")
        encoded_path = "/".join(
            quote(part, safe="")
            for part in clean_path.split("/")
            if part
        )

        url = (
            f"{self.GITHUB_API_BASE_URL}/repos/"
            f"{repository.owner}/{repository.name}/contents"
        )

        if encoded_path:
            url += f"/{encoded_path}"

        headers = self._api_headers(connection.access_token)

        with httpx.Client(timeout=20.0) as client:
            response = client.get(
                url,
                headers=headers,
                params={"ref": repository.default_branch},
            )

        if response.status_code == 404:
            raise FileNotFoundError(clean_path or ".")

        if response.status_code == 401:
            raise RuntimeError("GitHub access token was rejected.")

        if response.status_code != 200:
            raise RuntimeError(
                "GitHub repository contents lookup failed: "
                f"{response.status_code} {response.text[:500]}"
            )

        data = response.json()

        # GitHub returns an object for a single file and a list for a directory.
        if isinstance(data, dict):
            data = [data]

        return [
            {
                "name": item.get("name"),
                "type": (
                    "directory"
                    if item.get("type") == "dir"
                    else "file"
                ),
                "path": item.get("path"),
                "size": item.get("size", 0),
                "html_url": item.get("html_url"),
            }
            for item in data
            if item.get("type") in {"file", "dir"}
        ]



    def create_repository(
        self,
        student_id: str,
        name: str,
        description: str | None = None,
        private: bool = False,
    ) -> dict:
        name = name.strip()
        if not name:
            raise ValueError("Repository name cannot be empty.")
        connection = self._get_valid_connection(student_id)
        payload = {"name": name, "private": False, "auto_init": True}
        if description and description.strip():
            payload["description"] = description.strip()
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                f"{self.GITHUB_API_BASE_URL}/user/repos",
                headers=self._api_headers(connection.access_token),
                json=payload,
            )
        if response.status_code == 422:
            raise ValueError(
                "GitHub could not create that repository. "
                "The name may already exist or be invalid."
            )

        if response.status_code == 403:
            raise RuntimeError(
                "GitHub denied repository creation. For this GitHub App, "
                "make sure the app has Administration: Read and write, is "
                "installed on the student's account, and reconnect GitHub "
                "after changing the app's permissions."
            )

        if response.status_code not in {200, 201}:
            raise RuntimeError(
                "GitHub repository creation failed: "
                f"{response.status_code} {response.text[:500]}"
            )
        data = response.json()
        saved = self.save_repository(
            student_id=student_id, github_repo_id=str(data["id"]),
            owner=data["owner"]["login"], name=data["name"],
            full_name=data["full_name"], default_branch=data.get("default_branch") or "main",
        )
        return {
            "id": saved.id, "github_repo_id": saved.github_repo_id,
            "owner": saved.owner, "name": saved.name,
            "full_name": saved.full_name, "default_branch": saved.default_branch,
            "private": bool(data.get("private", False)),
            "html_url": data.get("html_url"),
            "description": data.get("description"),
        }

    def fetch_repository_file(
        self, student_id: str, repository_id: str, path: str
    ) -> dict:
        connection = self._get_valid_connection(student_id)
        repository = self.get_repository(repository_id)
        if repository is None or repository.student_id != student_id:
            raise ValueError("GitHub repository not found.")
        clean_path = path.strip().strip("/")
        if not clean_path:
            raise ValueError("File path cannot be empty.")
        encoded_path = "/".join(quote(part, safe="") for part in clean_path.split("/") if part)
        url = f"{self.GITHUB_API_BASE_URL}/repos/{repository.owner}/{repository.name}/contents/{encoded_path}"
        with httpx.Client(timeout=20.0) as client:
            response = client.get(url, headers=self._api_headers(connection.access_token), params={"ref": repository.default_branch})
        if response.status_code == 404:
            raise FileNotFoundError(clean_path)
        if response.status_code != 200:
            raise RuntimeError(f"GitHub file lookup failed: {response.status_code} {response.text[:500]}")
        data = response.json()
        if data.get("type") != "file" or not data.get("download_url"):
            raise ValueError("The selected GitHub path is not a readable file.")
        with httpx.Client(timeout=20.0) as client:
            content_response = client.get(data["download_url"], headers=self._api_headers(connection.access_token))
        if content_response.status_code != 200:
            raise RuntimeError("GitHub file download failed.")
        return {"path": clean_path, "content": content_response.text}

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