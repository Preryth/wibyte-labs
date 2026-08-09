from dataclasses import dataclass
from datetime import datetime


@dataclass
class LabSession:
    id: str
    container_id: str
    status: str
    created_at: datetime