from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, model_validator

from app.core.database import get_db
from app.models.ambulance import AmbulanceCreate, AmbulanceInDB
from app.models.location import Location
from app.services.eta_service import _haversine_km

router = APIRouter(prefix="/ambulances", tags=["ambulances"])


class AmbulanceUpdate(BaseModel):
    location: Location | None = None
    type: Literal["BLS", "ALS"] | None = None
    status: Literal["ACTIVE", "BUSY", "OFFLINE"] | None = None

    @model_validator(mode="after")
    def _require_at_least_one_field(self) -> "AmbulanceUpdate":
        if self.location is None and self.type is None and self.status is None:
            raise ValueError("at least one of location, type or status must be provided")
        return self


@router.get("", response_model=list[AmbulanceInDB])
async def list_ambulances(
    status: Literal["ACTIVE", "BUSY", "OFFLINE"] | None = Query(
        None, description="Filter by ambulance status"
    ),
    lat: float | None = Query(None, ge=-90, le=90, description="Latitude for nearby search"),
    lng: float | None = Query(None, ge=-180, le=180, description="Longitude for nearby search"),
    radius_km: float | None = Query(None, gt=0, description="Search radius in kilometers"),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> list[AmbulanceInDB]:
    """List all ambulances, optionally filtered by status and/or location radius."""
    filter_params = (lat, lng, radius_km)
    if any(value is not None for value in filter_params) and not all(
        value is not None for value in filter_params
    ):
        raise HTTPException(
            status_code=422,
            detail="lat, lng and radius_km must be provided together",
        )

    query = {"status": status} if status is not None else {}
    documents = await db["ambulances"].find(query).to_list(length=None)
    if lat is not None:
        documents = [
            doc
            for doc in documents
            if _haversine_km(lat, lng, doc["location"]["lat"], doc["location"]["lng"]) <= radius_km
        ]
    return [AmbulanceInDB(**doc) for doc in documents]


@router.post("", response_model=AmbulanceInDB, status_code=201)
async def register_ambulance(
    payload: AmbulanceCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> AmbulanceInDB:
    """Register a new ambulance. `ambulance_id` must be unique."""
    if await db["ambulances"].find_one({"ambulance_id": payload.ambulance_id}) is not None:
        raise HTTPException(status_code=409, detail="Ambulance already registered")

    document = payload.model_dump()
    inserted = await db["ambulances"].insert_one(document)
    saved = await db["ambulances"].find_one({"_id": inserted.inserted_id})
    return AmbulanceInDB(**saved)


@router.get("/{ambulance_id}", response_model=AmbulanceInDB)
async def get_ambulance(
    ambulance_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> AmbulanceInDB:
    """Fetch a single ambulance by its `ambulance_id`."""
    document = await db["ambulances"].find_one({"ambulance_id": ambulance_id})
    if document is None:
        raise HTTPException(status_code=404, detail="Ambulance not found")
    return AmbulanceInDB(**document)


@router.patch("/{ambulance_id}", response_model=AmbulanceInDB)
async def update_ambulance(
    ambulance_id: str,
    payload: AmbulanceUpdate,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> AmbulanceInDB:
    """Update an ambulance's live location and/or status.

    This is the endpoint the ambulance app calls to push GPS position pings
    while en route (so ETA calculations use the current location).
    """
    if await db["ambulances"].find_one({"ambulance_id": ambulance_id}) is None:
        raise HTTPException(status_code=404, detail="Ambulance not found")

    updates = payload.model_dump(exclude_unset=True)
    await db["ambulances"].update_one({"ambulance_id": ambulance_id}, {"$set": updates})
    saved = await db["ambulances"].find_one({"ambulance_id": ambulance_id})
    return AmbulanceInDB(**saved)
