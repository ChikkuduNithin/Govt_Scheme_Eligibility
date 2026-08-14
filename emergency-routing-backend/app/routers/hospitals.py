from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database import get_db
from app.models.hospital import HospitalInDB
from app.models.hospital_status import HospitalStatusCreate, HospitalStatusInDB
from app.models.py_object_id import PyObjectId
from app.services.eta_service import _haversine_km

router = APIRouter(prefix="/hospitals", tags=["hospitals"])


class HospitalWithStatus(HospitalInDB):
    status: HospitalStatusInDB | None = None


@router.get("", response_model=list[HospitalInDB])
async def list_hospitals(
    lat: float | None = Query(None, ge=-90, le=90, description="Latitude for nearby search"),
    lng: float | None = Query(None, ge=-180, le=180, description="Longitude for nearby search"),
    radius_km: float | None = Query(None, gt=0, description="Search radius in kilometers"),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> list[HospitalInDB]:
    """List all hospitals.

    If `lat`, `lng` and `radius_km` are all provided, filters the results to
    hospitals within that radius using a haversine distance calculation.
    """
    filter_params = (lat, lng, radius_km)
    if any(value is not None for value in filter_params) and not all(value is not None for value in filter_params):
        raise HTTPException(
            status_code=422,
            detail="lat, lng and radius_km must be provided together",
        )

    documents = await db["hospitals"].find().to_list(length=None)
    if lat is not None:
        documents = [
            doc
            for doc in documents
            if _haversine_km(lat, lng, doc["location"]["lat"], doc["location"]["lng"]) <= radius_km
        ]
    return [HospitalInDB(**doc) for doc in documents]


@router.get("/{hospital_id}", response_model=HospitalWithStatus)
async def get_hospital(
    hospital_id: PyObjectId,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> HospitalWithStatus:
    """Fetch a single hospital together with its current status.

    Returns the hospital document with an additional `status` object containing
    the current capacity snapshot, or `null` if no status has been reported yet.
    """
    document = await db["hospitals"].find_one({"_id": hospital_id})
    if document is None:
        raise HTTPException(status_code=404, detail="Hospital not found")

    status_document = await db["hospital_status"].find_one({"hospital_id": str(hospital_id)})
    result = HospitalWithStatus(**document)
    if status_document is not None:
        result.status = HospitalStatusInDB(**status_document)
    return result


@router.get("/{hospital_id}/status", response_model=HospitalStatusInDB)
async def get_hospital_status(
    hospital_id: PyObjectId,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> HospitalStatusInDB:
    """Fetch the current capacity status for a single hospital."""
    if await db["hospitals"].find_one({"_id": hospital_id}) is None:
        raise HTTPException(status_code=404, detail="Hospital not found")

    status_document = await db["hospital_status"].find_one({"hospital_id": str(hospital_id)})
    if status_document is None:
        raise HTTPException(status_code=404, detail="Hospital status not found")
    return HospitalStatusInDB(**status_document)


@router.post("/{hospital_id}/status", response_model=HospitalStatusInDB)
async def upsert_hospital_status(
    hospital_id: PyObjectId,
    payload: HospitalStatusCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> HospitalStatusInDB:
    """Create or replace the capacity status for a hospital.

    This is how a hospital dashboard pushes live capacity updates. The status
    document is upserted by `hospital_id`; the path id takes precedence over any
    `hospital_id` in the body, and `updated_at` is stamped server-side.
    """
    if await db["hospitals"].find_one({"_id": hospital_id}) is None:
        raise HTTPException(status_code=404, detail="Hospital not found")

    update_data = payload.model_dump()
    update_data["hospital_id"] = str(hospital_id)
    update_data["updated_at"] = datetime.now(timezone.utc)

    await db["hospital_status"].replace_one(
        {"hospital_id": str(hospital_id)},
        update_data,
        upsert=True,
    )
    saved = await db["hospital_status"].find_one({"hospital_id": str(hospital_id)})
    return HospitalStatusInDB(**saved)
