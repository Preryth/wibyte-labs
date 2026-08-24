from datetime import datetime, timezone

from sqlalchemy import select

from backend.app.db.database import SessionLocal
from backend.app.models.lab import LabSession
from backend.app.models.lab_db import Lab
from backend.app.models.student import Student
from backend.app.models.github_repository import (
    GitHubRepository,
)


class LabService:
    def __init__(self):
        self.SessionLocal = SessionLocal

    # =========================================================
    # Development student
    # =========================================================

    def get_or_create_development_student(
        self,
    ) -> Student:
        """
        Temporary development-only student.

        This gives us one persistent student while we build
        the real student profile/authentication system.
        """

        db = self.SessionLocal()

        try:
            student = (
                db.execute(
                    select(Student)
                    .order_by(Student.created_at)
                )
                .scalars()
                .first()
            )

            if student is not None:
                return student

            student = Student()

            db.add(student)
            db.commit()
            db.refresh(student)

            return student

        finally:
            db.close()

    # =========================================================
    # Lab creation
    # =========================================================

    def add(
        self,
        session: LabSession,
        student_id: str,
        github_repository_id: str | None = None,
    ):
        """
        Persist a newly created lab session.

        The Docker container should already exist when this
        method is called.

        If a GitHub repository is supplied, verify that the
        repository belongs to the same student before linking
        it to the lab.
        """

        db = self.SessionLocal()

        try:
            repository = None

            if github_repository_id is not None:
                repository = db.get(
                    GitHubRepository,
                    github_repository_id,
                )

                if repository is None:
                    raise ValueError(
                        "GitHub repository not found."
                    )

                if repository.student_id != student_id:
                    raise ValueError(
                        "GitHub repository does not belong "
                        "to this student."
                    )

            lab = Lab(
                id=session.id,
                student_id=student_id,
                container_id=session.container_id,
                status=session.status,
                created_at=session.created_at,
                last_activity_at=session.created_at,
                github_repository_id=(
                    repository.id
                    if repository is not None
                    else None
                ),
            )

            db.add(lab)
            db.commit()
            db.refresh(lab)

            return lab

        finally:
            db.close()

    # =========================================================
    # Lab retrieval
    # =========================================================

    def get(
        self,
        lab_id: str,
    ) -> LabSession | None:
        """
        Retrieve a persisted lab and convert it to the
        LabSession object currently used by the terminal
        and workspace systems.

        GitHub repository information remains persisted on
        the database Lab record.
        """

        db = self.SessionLocal()

        try:
            lab = db.get(
                Lab,
                lab_id,
            )

            if lab is None:
                return None

            return LabSession(
                id=lab.id,
                container_id=lab.container_id,
                status=lab.status,
                created_at=lab.created_at,
            )

        finally:
            db.close()

    def attach_github_repository(
        self,
        lab_id: str,
        github_repository_id: str,
    ) -> bool:
        """Attach the student-owned repository that backs this Lab."""
        db = self.SessionLocal()
        try:
            lab = db.get(Lab, lab_id)
            if lab is None:
                return False
            repository = db.get(GitHubRepository, github_repository_id)
            if repository is None:
                raise ValueError("GitHub repository not found.")
            if repository.student_id != lab.student_id:
                raise ValueError("GitHub repository does not belong to this student.")
            lab.github_repository_id = repository.id
            db.commit()
            return True
        finally:
            db.close()

    # =========================================================
    # Lab removal
    # =========================================================

    def remove(
        self,
        lab_id: str,
    ):
        """
        Remove a lab record from the database.

        This removes only the lab session.

        It does NOT remove:
        - the student
        - the GitHub connection
        - the GitHub repository
        """

        db = self.SessionLocal()

        try:
            lab = db.get(
                Lab,
                lab_id,
            )

            if lab is None:
                return None

            db.delete(lab)
            db.commit()

            return lab

        finally:
            db.close()

    # =========================================================
    # Lab status
    # =========================================================

    def update_status(
        self,
        lab_id: str,
        status: str,
    ) -> bool:
        """
        Update the persisted lab status.
        """

        db = self.SessionLocal()

        try:
            lab = db.get(
                Lab,
                lab_id,
            )

            if lab is None:
                return False

            lab.status = status

            db.commit()

            return True

        finally:
            db.close()

    # =========================================================
    # Lab activity
    # =========================================================

    def update_activity(
        self,
        lab_id: str,
    ) -> bool:
        """
        Update the lab's last activity timestamp.

        This is used by the inactivity system.
        """

        db = self.SessionLocal()

        try:
            lab = db.get(
                Lab,
                lab_id,
            )

            if lab is None:
                return False

            lab.last_activity_at = datetime.now(
                timezone.utc
            )

            db.commit()

            return True

        finally:
            db.close()


    # =========================================================
    # Student profile
    # =========================================================

    def update_student_profile(
        self,
        student_id: str,
        name: str | None,
        email: str | None,
    ) -> Student | None:
        db = self.SessionLocal()

        try:
            student = db.get(Student, student_id)
            if student is None:
                return None

            student.name = name
            student.email = email
            student.updated_at = datetime.now(timezone.utc)

            db.commit()
            db.refresh(student)
            return student
        finally:
            db.close()


lab_service = LabService()