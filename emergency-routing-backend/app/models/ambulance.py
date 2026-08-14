from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.location import Location
from app.models.py_object_id import PyObjectId


class AmbulanceCreate(BaseModel):
    ambulance_id: str
    location: Location
    type: Literal["BLS", "ALS"]
    status: Literal["ACTIVE", "BUSY", "OFFLINE"]


class AmbulanceInDB(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: PyObjectId = Field(alias="_id")
    ambulance_id: str
    location: Location
    type: Literal["BLS", "ALS"]
    status: Literal["ACTIVE", "BUSY", "OFFLINE"]
