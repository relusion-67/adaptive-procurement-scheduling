from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models import BookingStatus


class FarmerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=1, max_length=20)
    village: str = Field(min_length=1, max_length=255)


class FarmerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str
    village: str
    created_at: datetime


class ProcurementCentreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    district: str
    daily_capacity: int
    active: bool


class ProcurementSlotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    centre_id: int
    slot_date: date
    start_time: time
    end_time: time
    capacity: int


class BookingCreate(BaseModel):
    farmer_id: int
    centre_id: int
    slot_id: int
    crop_type: str = Field(min_length=1, max_length=100)
    quantity_kg: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class BookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    farmer_id: int
    centre_id: int
    slot_id: int
    crop_type: str
    quantity_kg: Decimal
    status: BookingStatus
    created_at: datetime
