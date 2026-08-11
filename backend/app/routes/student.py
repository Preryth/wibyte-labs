from re import fullmatch

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.app.services.github_service import github_service
from backend.app.services.lab_service import lab_service

router = APIRouter(prefix="/student", tags=["Student"])

class StudentSettingsUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=255)

def normalise_name(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None

def normalise_email(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().lower()
    if not value:
        return None
    if fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) is None:
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    return value

def settings_response(student):
    connection = github_service.get_connection(student.id)
    return {
        "student": {
            "id": student.id,
            "name": student.name,
            "email": student.email,
            "created_at": student.created_at,
            "updated_at": student.updated_at,
        },
        "github": {
            "connected": connection is not None,
            "username": connection.github_username if connection else None,
            "connected_at": connection.connected_at if connection else None,
        },
    }

@router.get("/settings")
def get_student_settings():
    student = lab_service.get_or_create_development_student()
    return settings_response(student)

@router.put("/settings")
def update_student_settings(request: StudentSettingsUpdate):
    student = lab_service.get_or_create_development_student()
    updated = lab_service.update_student_profile(
        student_id=student.id,
        name=normalise_name(request.name),
        email=normalise_email(request.email),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Student not found.")
    return settings_response(updated)