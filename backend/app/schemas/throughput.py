from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ThroughputSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    centre_id: int
    snapshot_at: datetime
    avg_minutes_per_farmer: Decimal
