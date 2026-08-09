from datetime import datetime, timezone
from uuid import uuid4

import docker
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.app.models.lab import LabSession
from backend.app.routes.terminal import router as terminal_router
from backend.app.services.lab_service import lab_service
from backend.app.services.terminal_service import TerminalService


app = FastAPI(title="WPL Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(terminal_router)

docker_client = docker.from_env()

app.state.docker_client = docker_client
app.state.terminal_service = TerminalService(docker_client)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/labs")
def create_lab():
    container = docker_client.containers.run(
        "wpl-student:dev",
        detach=True,
        tty=True,
        stdin_open=True,
    )

    session_id = str(uuid4())

    session = LabSession(
        id=session_id,
        container_id=container.id,
        status="running",
        created_at=datetime.now(timezone.utc),
    )

    lab_service.add(session)

    return {
        "lab_id": session.id,
        "status": session.status,
    }


@app.delete("/labs/{lab_id}")
def delete_lab(lab_id: str):
    session = lab_service.get(lab_id)

    if session is None:
        raise HTTPException(status_code=404, detail="Lab not found")

    try:
        container = docker_client.containers.get(session.container_id)
        container.remove(force=True)
    except docker.errors.NotFound:
        pass

    session.status = "removed"
    lab_service.remove(lab_id)

    return {
        "lab_id": session.id,
        "status": session.status,
    }