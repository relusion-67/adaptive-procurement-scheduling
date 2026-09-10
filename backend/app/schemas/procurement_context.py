"""Response schemas for the centre-scoped agricultural reference context
(Milestone 2). Sourced from the plain dataclasses in
``app/services/procurement_context.py`` and
``app/services/reference_data.py`` - never from the ``ReferenceDataset``
ORM model directly - so no database internals (row id, imported_at,
raw_payload) leak into the API response.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ReferenceContextResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class CentreAgriculturalContextResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    centre_id: int
    district: str
    reference_facts: list[ReferenceContextResponse]
