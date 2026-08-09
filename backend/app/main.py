from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import docker

app = FastAPI(title="WPL Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

docker_client = docker.from_env()


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

    return {
        "container_id": container.id,
        "status": "running",
    }
@app.delete("/labs/{container_id}")
def delete_lab(container_id: str):
    container = docker_client.containers.get(container_id)

    container.remove(force=True)

    return {
        "container_id": container_id,
        "status": "removed",
    }