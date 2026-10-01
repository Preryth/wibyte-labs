
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import fcntl

import docker
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from backend.app.services.lab_service import lab_service
from backend.app.models.lab_db import Lab


class LabCreateRequest(BaseModel):
    replace_lab_ids: list[str] | None = None


@contextmanager
def student_lab_lock(student_id):
    # Shared by backend processes on this VPS.
    directory = Path("/tmp/wpl-lab-locks")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    name = sha256(str(student_id).encode()).hexdigest() + ".lock"
    with (directory / name).open("a") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "LAB_BUSY",
                    "message": "A lab is being opened elsewhere. Please try again shortly.",
                },
            )
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def create_single_lab(user, request, docker_client, create):
    with student_lab_lock(user.id):
        db = lab_service.SessionLocal()
        try:
            rows = db.execute(
                select(Lab.id, Lab.container_id)
                .where(Lab.student_id == user.id)
                .order_by(Lab.id)
            ).all()
        finally:
            db.close()

        existing = []
        for lab_id, container_id in rows:
            try:
                container = docker_client.containers.get(container_id)
            except docker.errors.NotFound:
                # A missing container cannot be resumed.
                lab_service.remove(lab_id)
            else:
                existing.append((lab_id, container))

        current_ids = sorted(lab_id for lab_id, _ in existing)
        confirmed = request.replace_lab_ids if request is not None else None

        if current_ids and (
            confirmed is None or sorted(set(confirmed)) != current_ids
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "LAB_ALREADY_OPEN",
                    "message": "Another lab is already open for your account.",
                    "lab_ids": current_ids,
                },
            )

        if confirmed and not current_ids:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "LAB_CHANGED",
                    "message": "The previous lab has already closed. Click Create Lab again.",
                },
            )

        # Only the exact labs explicitly confirmed may be terminated.
        for lab_id, container in existing:
            try:
                container.remove(force=True)
            except docker.errors.NotFound:
                pass
            except Exception:
                raise HTTPException(
                    status_code=502,
                    detail="Could not close the existing lab. No new lab was opened.",
                )
            lab_service.remove(lab_id)

        return create()
