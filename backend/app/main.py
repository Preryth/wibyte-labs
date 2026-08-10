import docker

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.app.routes.terminal import (
    router as terminal_router,
)
from backend.app.routes.workspace import (
    router as workspace_router,
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


app = FastAPI(
    title="WPL Backend"
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
# Docker client and services
# ---------------------------------------------------------

docker_client = docker.from_env()

workspace_service = WorkspaceService(
    docker_client
)

terminal_service = TerminalService(
    docker_client
)

app.state.docker_client = docker_client

app.state.terminal_service = (
    terminal_service
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


# ---------------------------------------------------------
# Health
# ---------------------------------------------------------

@app.get("/health")
def health_check():
    return {
        "status": "ok"
    }


# ---------------------------------------------------------
# Create lab
# ---------------------------------------------------------

@app.post("/labs")
def create_lab():

    # Get the persistent development student.
    #
    # Later this will be replaced by the
    # authenticated student's actual ID.

    student = (
        lab_service
        .get_or_create_development_student()
    )


    # Create the Docker container.

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


    # Create a database-compatible
    # LabSession object.

    from backend.app.models.lab import (
        LabSession,
    )

    from datetime import (
        datetime,
        timezone,
    )

    from uuid import uuid4


    session = LabSession(
        id=str(uuid4()),
        container_id=container.id,
        status="running",
        created_at=datetime.now(
            timezone.utc
        ),
    )


    # Persist the lab in SQLite.

    try:
        lab_service.add(
            session,
            student.id,
        )

    except Exception as exc:

        # If database creation fails,
        # don't leave an orphan Docker
        # container behind.

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


    return {
        "lab_id": session.id,
        "status": session.status,
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

    # Find the lab through the database.

    session = lab_service.get(
        lab_id
    )

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Lab not found",
        )


    # Remove the Docker container.

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
        # Container is already gone.
        pass

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to remove lab "
                f"container: {exc}"
            ),
        )


    # Remove the persistent lab record.

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