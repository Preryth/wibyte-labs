from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from fastapi.responses import RedirectResponse

from backend.app.services.github_service import (
    github_service,
)

from backend.app.services.lab_service import (
    lab_service,
)
from backend.app.services.git_service import GitService
from backend.app.auth import CurrentUser



router = APIRouter(
    prefix="/github",
    tags=["GitHub"],
)


class GitCommitRequest(BaseModel):
    message: str


class CreateRepositoryRequest(BaseModel):
    name: str
    description: str | None = None
    private: bool = False


def _git_service() -> GitService:
    service = getattr(router, "git_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Git service is not initialized.")
    return service


# =========================================================
# Configuration
# =========================================================

GITHUB_CALLBACK_URL = (
    "http://127.0.0.1:8000/github/callback"
)

GITHUB_FRONTEND_URL = (
    "http://localhost:5173"
)


# =========================================================
# Start GitHub OAuth
# =========================================================

@router.post("/connect")
def github_connect(user: CurrentUser = None):
    student = lab_service.get_or_create_student(user.id, user.email, user.name)
    existing_connection = github_service.get_connection(student.id)
    if existing_connection is not None:
        raise HTTPException(status_code=409, detail="A GitHub connection is already active. Delete the current connection before connecting another GitHub account.")
    try:
        authorization_url = github_service.get_authorization_url(student_id=student.id, redirect_uri=GITHUB_CALLBACK_URL)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"authorization_url": authorization_url}


# =========================================================
# GitHub OAuth callback
# =========================================================

@router.get("/callback")
def github_callback(
    code: str | None = Query(
        default=None
    ),
    state: str | None = Query(
        default=None
    ),
    error: str | None = Query(
        default=None
    ),
    error_description: str | None = Query(
        default=None
    ),
):
    """
    Receive the OAuth callback from GitHub,
    validate the signed state, exchange the
    authorization code, retrieve the GitHub
    account, and persist the connection.
    """

    if error:
        detail = (
            "GitHub authorization failed: "
            f"{error}"
        )

        if error_description:
            detail += (
                f" - {error_description}"
            )

        raise HTTPException(
            status_code=400,
            detail=detail,
        )

    if not code:
        raise HTTPException(
            status_code=400,
            detail=(
                "GitHub callback did not "
                "include an authorization code."
            ),
        )

    if not state:
        raise HTTPException(
            status_code=400,
            detail=(
                "GitHub callback did not "
                "include OAuth state."
            ),
        )

    try:
        student_id = (
            github_service
            .verify_oauth_state(
                state
            )
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    # OAuth may have been started before another connection
    # was created. Re-check here so the callback cannot
    # silently replace an existing active connection.
    existing_connection = github_service.get_connection(
        student_id
    )

    if existing_connection is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "A GitHub connection is already active. "
                "Delete the current connection before "
                "connecting another GitHub account."
            ),
        )

    try:
        connection = (
            github_service
            .connect_from_oauth(
                student_id=student_id,
                code=code,
            )
        )

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Failed to complete GitHub "
                f"OAuth connection: {exc}"
            ),
        )

    return RedirectResponse(
        url=(
            f"{GITHUB_FRONTEND_URL}"
            "?github=connected"
        ),
        status_code=302,
    )


# =========================================================
# GitHub connection status
# =========================================================

@router.get("/status")
def github_status(user: CurrentUser):
    """
    Return the current GitHub connection.

    Access tokens and refresh tokens are never returned.
    """

    student = lab_service.get_or_create_student(user.id, user.email, user.name)

    connection = (
        github_service
        .get_connection(
            student.id
        )
    )

    if connection is None:
        return {
            "connected": False,
            "student_id": student.id,
        }

    return {
        "connected": True,
        "student_id": student.id,
        "github_user_id": (
            connection.github_user_id
        ),
        "github_username": (
            connection.github_username
        ),
        "connected_at": (
            connection.connected_at
        ),
        "access_token_expires_at": (
            connection.access_token_expires_at
        ),
        "refresh_token_expires_at": (
            connection.refresh_token_expires_at
        ),
    }


# =========================================================
# Delete GitHub connection
# =========================================================

@router.delete("/connection")
def github_disconnect(
    user: CurrentUser,
):
    """
    Delete the student's active GitHub connection.

    This removes WPL's locally stored OAuth credentials.
    It does not delete the student's GitHub repositories
    or existing Lab records.
    """

    student = lab_service.get_or_create_student(user.id, user.email, user.name)

    deleted = github_service.delete_connection(
        student.id
    )

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="No GitHub connection is currently active.",
        )

    return {
        "status": "disconnected",
        "student_id": student.id,
    }




@router.post("/repositories")
def create_github_repository(request: CreateRepositoryRequest,
    user: CurrentUser = None):
    student = lab_service.get_or_create_student(user.id, user.email, user.name)
    try:
        return github_service.create_repository(
            student_id=student.id,
            name=request.name,
            description=request.description,
            private=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/labs/{lab_id}/workspace-repository")
def ensure_workspace_repository(lab_id: str,
    user: CurrentUser = None):
    """Create or attach the student's permanent wibyte-workspace repository and clone it into this Lab."""
    student = lab_service.get_or_create_student(user.id, user.email, user.name)
    session = lab_service.get_for_student(lab_id, user.id)
    if session is None:
        raise HTTPException(status_code=404, detail="Lab not found")

    try:
        repositories = github_service.fetch_github_repositories(student.id)
        repository = next((item for item in repositories if item.get("name") == "wibyte-workspace"), None)
        if repository is None:
            repository = github_service.create_repository(
                student_id=student.id,
                name="wibyte-workspace",
                description="WiByte Labs persistent workspace",
                private=False,
            )
        repository_id = repository["id"]
        lab_service.attach_github_repository(lab_id, repository_id)
        info = github_service.provision_repository(
            student_id=student.id,
            repository_id=repository_id,
            container_id=session.container_id,
        )
        return {"lab_id": lab_id, "repository": repository, "provision": info}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

# =========================================================
# Repository discovery
# =========================================================

@router.get("/repositories")
def github_repositories(
    refresh: bool = Query(default=True),
    user: CurrentUser = None,
):
    """
    Return repositories accessible to the connected
    GitHub account.

    By default, repositories are fetched from GitHub
    and synchronized into the local database.

    Set refresh=false to return the locally stored
    repository list without contacting GitHub.
    """

    student = lab_service.get_or_create_student(user.id, user.email, user.name)

    try:

        if refresh:
            repositories = (
                github_service
                .fetch_github_repositories(
                    student.id
                )
            )

            return {
                "student_id": student.id,
                "source": "github",
                "repositories": repositories,
            }

        repositories = (
            github_service
            .get_repositories(
                student.id
            )
        )

        return {
            "student_id": student.id,
            "source": "database",
            "repositories": [
                {
                    "id": repository.id,
                    "github_repo_id": (
                        repository.github_repo_id
                    ),
                    "owner": repository.owner,
                    "name": repository.name,
                    "full_name": (
                        repository.full_name
                    ),
                    "default_branch": (
                        repository.default_branch
                    ),
                }
                for repository in repositories
            ],
        }

    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        )

# =========================================================
# Repository contents browsing
# =========================================================

@router.get("/repositories/{repository_id}/contents")
def github_repository_contents(
    repository_id: str,
    path: str = Query(default=""),
    user: CurrentUser = None,
):
    """
    Browse one directory of a student's GitHub repository.

    This is read-only. Editing happens in the Docker workspace
    after the repository has been opened in a Lab.
    """
    student = lab_service.get_or_create_student(user.id, user.email, user.name)

    try:
        contents = github_service.fetch_repository_contents(
            student_id=student.id,
            repository_id=repository_id,
            path=path,
        )

        return {
            "repository_id": repository_id,
            "path": path,
            "contents": contents,
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Repository path not found.",
        )

    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        )


# =========================================================
# Git operations for the active GitHub-backed Lab
# =========================================================

@router.get("/labs/{lab_id}/git/status")
def git_status(lab_id: str, user: CurrentUser = None):
    if lab_service.get_for_student(lab_id, user.id) is None:
        raise HTTPException(status_code=404, detail="Lab not found")
    try:
        return _git_service().status(lab_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/labs/{lab_id}/git/diff")
def git_diff(lab_id: str, path: str | None = Query(default=None), user: CurrentUser = None):
    if lab_service.get_for_student(lab_id, user.id) is None:
        raise HTTPException(status_code=404, detail="Lab not found")
    try:
        return _git_service().diff(lab_id, path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/labs/{lab_id}/git/commit")
def git_commit(lab_id: str, request: GitCommitRequest, user: CurrentUser = None):
    if lab_service.get_for_student(lab_id, user.id) is None:
        raise HTTPException(status_code=404, detail="Lab not found")
    try:
        return _git_service().commit(lab_id, request.message)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/labs/{lab_id}/git/push")
def git_push(lab_id: str, user: CurrentUser = None):
    if lab_service.get_for_student(lab_id, user.id) is None:
        raise HTTPException(status_code=404, detail="Lab not found")
    try:
        return _git_service().push(lab_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/labs/{lab_id}/git/pull")
def git_pull(lab_id: str, user: CurrentUser = None):
    if lab_service.get_for_student(lab_id, user.id) is None:
        raise HTTPException(status_code=404, detail="Lab not found")
    try:
        return _git_service().pull(lab_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


router.git_service = None
