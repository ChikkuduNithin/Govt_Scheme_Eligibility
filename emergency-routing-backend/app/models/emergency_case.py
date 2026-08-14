from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.py_object_id import PyObjectId

EmergencyType = Literal[
    "TRAUMA",
    "STROKE",
    "CARDIAC",
    "RESPIRATORY",
    "BURN",
    "PEDIATRIC",
    "OBSTETRIC",
    "GENERAL_CRITICAL",
]


class PatientInfo(BaseModel):
    age: int = Field(ge=0, le=120, description="Patient age in years")
    conscious: bool
    spo2: int = Field(ge=0, le=100, description="Oxygen saturation percentage")
    heart_rate: int = Field(ge=0, le=300, description="Heart rate in bpm")
    bp: str = Field(pattern=r"^\d{2,3}/\d{2,3}$", description="Blood pressure as systolic/diastolic")


class EmergencyCaseCreate(BaseModel):
    case_id: str
    emergency_type: EmergencyType
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    patient: PatientInfo
    ambulance_id: str
    status: Literal["OPEN", "RECOMMENDED", "ACCEPTED", "CLOSED"]


class EmergencyCaseRequest(BaseModel):
    emergency_type: EmergencyType
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    patient: PatientInfo
    ambulance_id: str


class EmergencyCaseInDB(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: PyObjectId = Field(alias="_id")
    case_id: str
    emergency_type: EmergencyType
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    patient: PatientInfo
    ambulance_id: str
    status: Literal["OPEN", "RECOMMENDED", "ACCEPTED", "CLOSED"]
    created_at: datetime
