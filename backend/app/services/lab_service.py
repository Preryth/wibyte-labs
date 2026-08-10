from sqlalchemy import select

from backend.app.db.database import SessionLocal
from backend.app.models.lab import LabSession
from backend.app.models.lab_db import Lab
from backend.app.models.student import Student


class LabService:
    def __init__(self):
        self.SessionLocal = SessionLocal

    def get_or_create_development_student(self) -> Student:
        """
        Temporary development-only student.

        This gives us one persistent student while we build
        the real student profile/authentication system.
        """

        db = self.SessionLocal()

        try:
            student = db.execute(
                select(Student)
                .order_by(Student.created_at)
            ).scalars().first()

            if student is not None:
                return student

            student = Student()

            db.add(student)
            db.commit()
            db.refresh(student)

            return student

        finally:
            db.close()

    def add(
        self,
        session: LabSession,
        student_id: str,
    ):
        """
        Persist a lab session in the database.
        """

        db = self.SessionLocal()

        try:
            lab = Lab(
                id=session.id,
                student_id=student_id,
                container_id=session.container_id,
                status=session.status,
                created_at=session.created_at,
                last_activity_at=session.created_at,
            )

            db.add(lab)
            db.commit()
            db.refresh(lab)

            return lab

        finally:
            db.close()

    def get(
        self,
        lab_id: str,
    ) -> LabSession | None:
        """
        Retrieve a lab from the database and convert it
        to the LabSession object currently used by the
        terminal and workspace systems.
        """

        db = self.SessionLocal()

        try:
            lab = db.get(Lab, lab_id)

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

    def remove(
        self,
        lab_id: str,
    ):
        """
        Remove the lab record from the database.
        """

        db = self.SessionLocal()

        try:
            lab = db.get(Lab, lab_id)

            if lab is None:
                return None

            db.delete(lab)
            db.commit()

            return lab

        finally:
            db.close()

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
            lab = db.get(Lab, lab_id)

            if lab is None:
                return False

            lab.status = status

            db.commit()

            return True

        finally:
            db.close()

    def update_activity(
        self,
        lab_id: str,
    ) -> bool:
        """
        Update the lab's last activity timestamp.

        This will later be used by the 30-minute
        inactivity system.
        """

        from datetime import datetime, timezone

        db = self.SessionLocal()

        try:
            lab = db.get(Lab, lab_id)

            if lab is None:
                return False

            lab.last_activity_at = datetime.now(
                timezone.utc
            )

            db.commit()

            return True

        finally:
            db.close()


lab_service = LabService()