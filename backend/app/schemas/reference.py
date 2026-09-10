from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ReferenceDatasetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dataset_type: str
    district: str
    season_or_period: str
    metric_name: str
    metric_value: Decimal
    unit: str
    data_status: str
    source: str | None
    source_reference: str | None
    retrieved_at: datetime | None
    imported_at: datetime
