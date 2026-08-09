from backend.app.models.lab import LabSession


class LabService:
    def __init__(self):
        self.sessions: dict[str, LabSession] = {}

    def add(self, session: LabSession):
        self.sessions[session.id] = session

    def get(self, lab_id: str) -> LabSession | None:
        return self.sessions.get(lab_id)

    def remove(self, lab_id: str):
        return self.sessions.pop(lab_id, None)


lab_service = LabService()