import asyncio
import docker

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.app.models.lab import LabSession

from backend.app.routes.terminal import (
    router as terminal_router,
)

from backend.app.routes.workspace import (
    router as workspace_router,
)

from backend.app.routes.github import (
    router as github_router,
)

from backend.app.services.lab_service import (
    lab_service,
)

from backend.app.services.terminal_service import (
    TerminalService,
)

from backend.app.services.workspace_service import (
    WorkspaceService,
)

from backend.app.services.inactivity_service import (
    InactivityService,
)

from backend.app.services.github_service import (
    github_service,
)


# ---------------------------------------------------------
# Docker client and services
# ---------------------------------------------------------

docker_client = docker.from_env()

workspace_service = WorkspaceService(
    docker_client
)

terminal_service = TerminalService(
    docker_client
)

inactivity_service = InactivityService(
    docker_client
)


# ---------------------------------------------------------
# FastAPI lifespan
# ---------------------------------------------------------

@asynccontextmanager
async def lifespan(
    app: FastAPI,
):
    """
    Start background services when FastAPI starts
    and stop them cleanly when FastAPI shuts down.
    """

    inactivity_task = asyncio.create_task(
        inactivity_service.run_forever()
    )

    print(
        "[WPL] Inactivity cleanup worker started."
    )

    try:
        yield

    finally:
        print(
            "[WPL] Stopping inactivity cleanup worker."
        )

        inactivity_task.cancel()

        try:
            await inactivity_task

        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------

app = FastAPI(
    title="WPL Backend",
    lifespan=lifespan,
)


# ---------------------------------------------------------
# CORS
# ---------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------
# Application state
# ---------------------------------------------------------

app.state.docker_client = (
    docker_client
)

app.state.lab_service = (
    lab_service
)

app.state.terminal_service = (
    terminal_service
)

app.state.workspace_service = (
    workspace_service
)

app.state.inactivity_service = (
    inactivity_service
)

app.state.github_service = (
    github_service
)


# ---------------------------------------------------------
# Routers
# ---------------------------------------------------------

app.include_router(
    terminal_router
)

workspace_router.workspace_service = (
    workspace_service
)

app.include_router(
    workspace_router
)

app.include_router(
    github_router
)


# ---------------------------------------------------------
# Health
# ---------------------------------------------------------

@app.get("/health")
def health_check():
    return {
        "status": "ok",
    }


# ---------------------------------------------------------
# Create lab
# ---------------------------------------------------------

@app.post("/labs")
def create_lab(
    github_repository_id: str | None = Query(
        default=None,
    ),
):
    """
    Create a new temporary lab for the persistent
    development student.

    If github_repository_id is provided:

        1. Verify that the repository belongs to
           the development student.
        2. Create the Docker container.
        3. Persist the Lab.
        4. Download the repository from GitHub.
        5. Put the repository contents into /workspace.

    The GitHub access token remains in the backend
    and is never passed into the Docker container.
    """

    student = (
        lab_service
        .get_or_create_development_student()
    )

    # -----------------------------------------------------
    # Create Docker container
    # -----------------------------------------------------

    try:
        container = (
            docker_client
            .containers
            .run(
                "wpl-student:dev",
                detach=True,
                tty=True,
                stdin_open=True,
            )
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to create lab "
                f"container: {exc}"
            ),
        )

    session = LabSession(
        id=str(uuid4()),
        container_id=container.id,
        status="running",
        created_at=datetime.now(
            timezone.utc
        ),
    )

    # -----------------------------------------------------
    # Persist Lab
    # -----------------------------------------------------

    try:
        lab_service.add(
            session,
            student.id,
            github_repository_id,
        )

    except ValueError as exc:

        try:
            container.remove(
                force=True
            )

        except Exception:
            pass

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:

        try:
            container.remove(
                force=True
            )

        except Exception:
            pass

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to create lab "
                f"record: {exc}"
            ),
        )

    # -----------------------------------------------------
    # Provision GitHub repository
    # -----------------------------------------------------

    repository_info = None

    if github_repository_id is not None:

        try:
            repository_info = (
                github_service
                .provision_repository(
                    student_id=student.id,
                    repository_id=(
                        github_repository_id
                    ),
                    container_id=container.id,
                )
            )

        except ValueError as exc:

            # Remove the database Lab.
            try:
                lab_service.remove(
                    session.id
                )
            except Exception:
                pass

            # Remove the Docker container.
            try:
                container.remove(
                    force=True
                )
            except Exception:
                pass

            raise HTTPException(
                status_code=400,
                detail=str(exc),
            )

        except Exception as exc:

            # Remove the database Lab.
            try:
                lab_service.remove(
                    session.id
                )
            except Exception:
                pass

            # Remove the Docker container.
            try:
                container.remove(
                    force=True
                )
            except Exception:
                pass

            raise HTTPException(
                status_code=502,
                detail=(
                    "Failed to provision GitHub "
                    f"repository: {exc}"
                ),
            )

    # -----------------------------------------------------
    # Success
    # -----------------------------------------------------

    return {
        "lab_id": session.id,
        "status": session.status,
        "github_repository_id": (
            github_repository_id
        ),
        "repository": repository_info,
    }


# ---------------------------------------------------------
# Record lab activity
# ---------------------------------------------------------

@app.post(
    "/labs/{lab_id}/activity"
)
def record_lab_activity(
    lab_id: str,
):
    """
    Record meaningful user activity in the lab.
    """

    updated = (
        lab_service
        .update_activity(
            lab_id
        )
    )

    if not updated:
        raise HTTPException(
            status_code=404,
            detail="Lab not found",
        )

    return {
        "lab_id": lab_id,
        "status": "activity_recorded",
    }


# ---------------------------------------------------------
# Delete lab
# ---------------------------------------------------------

@app.delete(
    "/labs/{lab_id}"
)
def delete_lab(
    lab_id: str,
):
    """
    Permanently end a lab session.

    This deletes:
        - the Docker container
        - the lab database record

    This does NOT delete:
        - the student
        - the student's GitHub connection
        - the student's GitHub repositories
    """

    session = lab_service.get(
        lab_id
    )

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Lab not found",
        )

    try:
        container = (
            docker_client
            .containers
            .get(
                session.container_id
            )
        )

        container.remove(
            force=True
        )

    except docker.errors.NotFound:
        pass

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to remove lab "
                f"container: {exc}"
            ),
        )

    removed = lab_service.remove(
        lab_id
    )

    if removed is None:
        raise HTTPException(
            status_code=404,
            detail="Lab not found",
        )

    return {
        "lab_id": lab_id,
        "status": "removed",
    }