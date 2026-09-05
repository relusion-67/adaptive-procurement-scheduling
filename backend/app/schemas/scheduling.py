from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.services.scheduling import SchedulingRecommendation, SchedulingStatus

__all__ = [
    "SchedulingStatus",
    "SchedulingRecommendation",
    "SchedulingAssessmentResponse",
]


class SchedulingAssessmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    booking_id: int
    centre_id: int
    slot_id: int
    scheduling_status: SchedulingStatus
    recommendation: SchedulingRecommendation
    farmers_ahead: int
    average_service_minutes: Decimal
    estimated_wait_minutes: Decimal
    estimated_completion_time: datetime
    slot_end_time: datetime
    is_forecast: bool
    recommended_slot_id: int | None
    recommended_centre_id: int | None
    explanation: str
    calculated_at: datetime
