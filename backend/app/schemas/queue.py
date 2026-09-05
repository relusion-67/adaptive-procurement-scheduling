from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import QueueStatus


class QueueCheckInCreate(BaseModel):
    booking_id: int
    centre_id: int


class QueueEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    centre_id: int
    booking_id: int
    token_number: int
    queue_status: QueueStatus
    checked_in_at: datetime | None
    called_at: datetime | None
    served_at: datetime | None
