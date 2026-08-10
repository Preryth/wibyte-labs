from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from backend.app.services.github_service import (
    github_service,
)

from backend.app.services.lab_service import (
    lab_service,
)


router = APIRouter(
    prefix="/github",
    tags=["GitHub"],
)


# =========================================================
# Configuration
# =========================================================

GITHUB_CALLBACK_URL = (
    "http://127.0.0.1:8000/github/callback"
)


# =========================================================
# Start GitHub OAuth
# =========================================================

@router.get("/connect")
def github_connect():
    """
    Start the GitHub OAuth authorization flow.

    For development we currently use the persistent
    development student.

    Later this student ID will come from the authenticated
    WPL user session.
    """

    student = (
        lab_service
        .get_or_create_development_student()
    )

    try:
        authorization_url = (
            github_service
            .get_authorization_url(
                student_id=student.id,
                redirect_uri=GITHUB_CALLBACK_URL,
            )
        )

    except RuntimeError as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )

    return RedirectResponse(
        url=authorization_url,
        status_code=302,
    )


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

    return {
        "status": "connected",
        "student_id": connection.student_id,
        "github_user_id": (
            connection.github_user_id
        ),
        "github_username": (
            connection.github_username
        ),
        "connected_at": (
            connection.connected_at
        ),
    }


# =========================================================
# GitHub connection status
# =========================================================

@router.get("/status")
def github_status():
    """
    Return the current GitHub connection.

    Access tokens and refresh tokens are never returned.
    """

    student = (
        lab_service
        .get_or_create_development_student()
    )

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
# Repository discovery
# =========================================================

@router.get("/repositories")
def github_repositories(
    refresh: bool = Query(
        default=True
    ),
):
    """
    Return repositories accessible to the connected
    GitHub account.

    By default, repositories are fetched from GitHub
    and synchronized into the local database.

    Set refresh=false to return the locally stored
    repository list without contacting GitHub.
    """

    student = (
        lab_service
        .get_or_create_development_student()
    )

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