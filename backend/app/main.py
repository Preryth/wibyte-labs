import asyncio
import docker
from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.app.models.lab import LabSession
from backend.app.auth import CurrentUser

from backend.app.routes.terminal import (
    router as terminal_router,
)

from backend.app.routes.workspace import (
    router as workspace_router,
)

from backend.app.routes.github import (
    router as github_router,
)
from backend.app.routes.student import (
    router as student_router,
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

from backend.app.services.gui_service import (
    GuiService,
)
from backend.app.services.git_service import (
    GitService,
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

gui_service = GuiService(
    docker_client
)

git_service = GitService(
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

app.state.gui_service = (
    gui_service
)

app.state.git_service = (
    git_service
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

github_router.git_service = git_service

app.include_router(
    github_router
)
app.include_router(
    student_router
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
def create_lab(user: CurrentUser):
    """Create a temporary Lab. GitHub remains the persistent source of truth.

    The Lab starts empty when the permanent repository does not yet exist.
    The frontend can then ask the student to create it. If it already exists,
    it is cloned immediately into /workspace/wibyte-workspace.
    """
    student = lab_service.get_or_create_student(user.id, user.email, user.name)
    try:
        container = docker_client.containers.run(
            "wpl-student:dev", detach=True, tty=True, stdin_open=True,
            ports={"6080/tcp": None},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create lab container: {exc}")

    mkdir_result = container.exec_run(
        ["mkdir", "-p", "/workspace/wibyte-workspace"],
        user="root",
    )
    if mkdir_result.exit_code != 0:
        try: container.remove(force=True)
        except Exception: pass
        raise HTTPException(status_code=500, detail="Failed to create Lab workspace directory.")
    container.exec_run(["chown", "-R", "student:student", "/workspace"], user="root")

    session = LabSession(
        id=str(uuid4()), container_id=container.id, status="running",
        created_at=datetime.now(timezone.utc),
    )
    try:
        lab_service.add(session, student.id)
        repository = None
        repository_missing = False
        connection = github_service.get_connection(student.id)
        if connection is None:
            repository_missing = True
        else:
            repositories = github_service.fetch_github_repositories(student.id)
            repository = next((item for item in repositories if item.get("name") == "wibyte-workspace"), None)
            if repository is None:
                repository_missing = True
            else:
                lab_service.attach_github_repository(session.id, repository["id"])
                github_service.provision_repository(
                    student_id=student.id, repository_id=repository["id"],
                    container_id=container.id,
                )
        return {
            "lab_id": session.id, "status": session.status,
            "repository": repository,
            "repository_missing": repository_missing,
            "github_connected": connection is not None,
        }
    except ValueError as exc:
        try: lab_service.remove(session.id)
        except Exception: pass
        try: container.remove(force=True)
        except Exception: pass
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        try: lab_service.remove(session.id)
        except Exception: pass
        try: container.remove(force=True)
        except Exception: pass
        raise HTTPException(status_code=502, detail=f"Failed to prepare Lab workspace: {exc}")


# ---------------------------------------------------------
# GUI environment
# ---------------------------------------------------------

@app.get(
    "/labs/{lab_id}/gui/status"
)
def gui_status(
    lab_id: str,
    user: CurrentUser):
    """
    Return the GUI-process status for an existing Lab without
    starting the GUI environment.
    """

    session = lab_service.get_for_student(
        lab_id, user.id
    )

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Lab not found",
        )

    try:
        return {
            "lab_id": lab_id,
            **gui_service.status(
                session.container_id
            ),
        }

    except docker.errors.NotFound:
        raise HTTPException(
            status_code=404,
            detail="Lab container not found",
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to inspect GUI environment: "
                f"{exc}"
            ),
        )


@app.post(
    "/labs/{lab_id}/gui/start"
)
def start_gui(
    lab_id: str,
    user: CurrentUser):
    """
    Start Xvfb, Fluxbox, x11vnc, and websockify/noVNC inside the
    existing Lab container.

    This does not create another Lab or another container.
    Calling it again reuses the existing GUI processes.
    """

    session = lab_service.get_for_student(
        lab_id, user.id
    )

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Lab not found",
        )

    try:
        status = gui_service.start(
            session.container_id
        )

        return {
            "lab_id": lab_id,
            "status": "gui_ready",
            **status,
        }

    except docker.errors.NotFound:
        raise HTTPException(
            status_code=404,
            detail="Lab container not found",
        )

    except RuntimeError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to start GUI environment: "
                f"{exc}"
            ),
        )


# ---------------------------------------------------------
# GUI browser connection
# ---------------------------------------------------------

@app.get(
    "/labs/{lab_id}/gui/connection"
)
def gui_connection(
    lab_id: str,
    user: CurrentUser):
    """
    Return the browser URL for this Lab's noVNC server.

    The GUI must already be started. The Lab container exposes only
    websockify/noVNC on a dynamically assigned host port; x11vnc
    itself remains localhost-only inside the container.
    """

    session = lab_service.get_for_student(
        lab_id, user.id
    )

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Lab not found",
        )

    try:
        status = gui_service.status(
            session.container_id
        )

        if not status["ready"]:
            raise HTTPException(
                status_code=409,
                detail=(
                    "GUI environment is not ready. "
                    "Start the GUI first."
                ),
            )

        container = (
            docker_client
            .containers
            .get(
                session.container_id
            )
        )
        container.reload()

        port_bindings = (
            container.attrs
            .get("NetworkSettings", {})
            .get("Ports", {})
        )
        bindings = port_bindings.get(
            f"{gui_service.WEB_PORT}/tcp"
        )

        if not bindings:
            raise RuntimeError(
                "GUI web port is not published for this Lab container. "
                "Create a new Lab after applying the GUI streaming update."
            )

        host_port = bindings[0].get(
            "HostPort"
        )

        if not host_port:
            raise RuntimeError(
                "GUI web port does not have a host binding."
            )

        url = (
            f"http://127.0.0.1:{host_port}/vnc.html"
            "?autoconnect=true&resize=scale"
        )

        return {
            "lab_id": lab_id,
            "url": url,
            "web_port": gui_service.WEB_PORT,
            "host_port": int(host_port),
        }

    except docker.errors.NotFound:
        raise HTTPException(
            status_code=404,
            detail="Lab container not found",
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to create GUI browser connection: "
                f"{exc}"
            ),
        )


# ---------------------------------------------------------
# Record lab activity
# ---------------------------------------------------------

@app.post(
    "/labs/{lab_id}/activity"
)
def record_lab_activity(
    lab_id: str,
    user: CurrentUser):
    """
    Record meaningful user activity in the lab.
    """

    if lab_service.get_for_student(lab_id, user.id) is None:
        raise HTTPException(status_code=404, detail="Lab not found")

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
    user: CurrentUser):
    """
    Permanently end a lab session.

    This deletes:
        - the Docker container
        - the lab database record

    This does NOT delete:
        - the student
        - the student's GitHub connection
        - the student's GitHub repositories

    The GUI environment, if started, lives inside the same Docker
    container and therefore ends automatically with the Lab.
    """

    session = lab_service.get_for_student(
        lab_id, user.id
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
