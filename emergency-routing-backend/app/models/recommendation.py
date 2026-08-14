from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.py_object_id import PyObjectId


class AlternativeHospital(BaseModel):
    hospital_id: str
    eliminated_reason: str | None = None
    total_care_delay_minutes: float | None = None


class RecommendationCreate(BaseModel):
    case_id: str
    recommended_hospital_id: str | None = None
    eta_minutes: float | None = None
    total_care_delay_minutes: float | None = None
    reasons: list[str] = []
    alternatives: list[AlternativeHospital] = []
    no_eligible_hospital: bool = False


class RecommendationInDB(RecommendationCreate):
    model_config = ConfigDict(populate_by_name=True)

    id: PyObjectId = Field(alias="_id")
    created_at: datetime
