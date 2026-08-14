from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.location import Location
from app.models.py_object_id import PyObjectId


class HospitalCapabilities(BaseModel):
    emergency: bool = False
    trauma: bool = False
    icu: bool = False
    cardiology: bool = False
    neurology: bool = False
    ct: bool = False
    cath_lab: bool = False
    blood_bank: bool = False
    surgery: bool = False
    pediatrics: bool = False
    obstetrics: bool = False


class HospitalCreate(BaseModel):
    name: str
    location: Location
    capabilities: HospitalCapabilities


class HospitalInDB(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: PyObjectId = Field(alias="_id")
    name: str
    location: Location
    capabilities: HospitalCapabilities
    created_at: datetime
