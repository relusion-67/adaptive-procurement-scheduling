from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.schemas.procurement_context import ReferenceContextResponse
from app.schemas.scheduling import SchedulingAssessmentResponse
from app.services.scheduling import SchedulingStatus


class OperationalMetricsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    queue_depth: int
    active_booking_count: int
    current_serving_token: int | None
    average_service_minutes: Decimal | None
    estimated_wait_minutes: Decimal | None


class AttentionItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    title: str
    detail: str
    evidence: list[str]


class OperationalRecommendationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    title: str
    explanation: str
    evidence: list[str]
    severity: str
    priority: int


class ProcurementInsightResponse(BaseModel):
    centre_id: int
    centre_name: str
    centre_code: str
    district: str
    operational_status: SchedulingStatus
    metrics: OperationalMetricsResponse
    reasons: list[str]
    attention_items: list[AttentionItemResponse]
    recommendations: list[OperationalRecommendationResponse]
    booking_assessments: list[SchedulingAssessmentResponse]
    reference_context: list[ReferenceContextResponse]
    calculated_at: datetime
