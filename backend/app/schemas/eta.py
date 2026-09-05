from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models import QueueStatus


class QueueETAResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    queue_entry_id: int
    token_number: int
    queue_position: int
    farmers_ahead: int
    average_service_minutes: Decimal
    estimated_wait_minutes: Decimal
    queue_status: QueueStatus
    calculated_at: datetime
