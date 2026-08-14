from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.py_object_id import PyObjectId

AvailabilityStatus = Literal["AVAILABLE", "UNAVAILABLE"]


class HospitalStatusCreate(BaseModel):
    hospital_id: str
    icu_available: int
    icu_total: int
    emergency_beds_available: int
    emergency_beds_total: int
    trauma_status: AvailabilityStatus
    cardiology_status: AvailabilityStatus
    neurology_status: AvailabilityStatus
    ct_status: AvailabilityStatus
    cath_lab_status: AvailabilityStatus
    accepting_patients: bool


class HospitalStatusInDB(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: PyObjectId = Field(alias="_id")
    hospital_id: str
    icu_available: int
    icu_total: int
    emergency_beds_available: int
    emergency_beds_total: int
    trauma_status: AvailabilityStatus
    cardiology_status: AvailabilityStatus
    neurology_status: AvailabilityStatus
    ct_status: AvailabilityStatus
    cath_lab_status: AvailabilityStatus
    accepting_patients: bool
    updated_at: datetime
