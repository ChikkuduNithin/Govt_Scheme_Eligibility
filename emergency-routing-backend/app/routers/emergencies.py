from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.core.database import get_db
from app.models.emergency_case import EmergencyCaseInDB, EmergencyCaseRequest
from app.models.py_object_id import PyObjectId
from app.models.recommendation import AlternativeHospital
from app.services.decision_engine import recommend_hospital

router = APIRouter(tags=["emergencies"])


class AcceptBody(BaseModel):
    hospital_id: PyObjectId


class RecommendationResponse(BaseModel):
    case_id: str
    recommended_hospital_id: str | None = None
    eta_minutes: float | None = None
    total_care_delay_minutes: float | None = None
    reasons: list[str] = []
    alternatives: list[AlternativeHospital] = []
    no_eligible_hospital: bool = False
    created_at: datetime


def _to_recommendation_response(document: dict) -> RecommendationResponse:
    return RecommendationResponse(
        case_id=document["case_id"],
        recommended_hospital_id=document.get("recommended_hospital_id"),
        eta_minutes=document.get("eta_minutes"),
        total_care_delay_minutes=document.get("total_care_delay_minutes"),
        reasons=document.get("reasons", []),
        alternatives=document.get("alternatives", []),
        no_eligible_hospital=document.get("no_eligible_hospital", False),
        created_at=document.get("created_at"),
    )


@router.post("/emergencies", response_model=EmergencyCaseInDB, status_code=201)
async def create_emergency_case(
    payload: EmergencyCaseRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> EmergencyCaseInDB:
    """Create a new emergency case.

    The server generates the `case_id` and creates the case in status `OPEN`.
    """
    document = {
        **payload.model_dump(),
        "case_id": f"case-{uuid4().hex}",
        "status": "OPEN",
        "created_at": datetime.now(timezone.utc),
    }
    inserted = await db["emergency_cases"].insert_one(document)
    saved = await db["emergency_cases"].find_one({"_id": inserted.inserted_id})
    return EmergencyCaseInDB(**saved)


@router.get("/emergencies/{case_id}", response_model=EmergencyCaseInDB)
async def get_emergency_case(
    case_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> EmergencyCaseInDB:
    """Fetch a single emergency case by its `case_id`."""
    document = await db["emergency_cases"].find_one({"case_id": case_id})
    if document is None:
        raise HTTPException(status_code=404, detail="Emergency case not found")
    return EmergencyCaseInDB(**document)


@router.post("/emergencies/{case_id}/recommend", response_model=RecommendationResponse)
async def recommend_for_case(
    case_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> RecommendationResponse:
    """Recommend the best hospital for an emergency case.

    Fetches the case, the assigned ambulance's location and all hospitals with
    their current statuses, runs the decision engine, stores the recommendation
    (upserted by `case_id`) and moves the case to `RECOMMENDED`.
    """
    case = await db["emergency_cases"].find_one({"case_id": case_id})
    if case is None:
        raise HTTPException(status_code=404, detail="Emergency case not found")

    ambulance = await db["ambulances"].find_one({"ambulance_id": case["ambulance_id"]})
    if ambulance is None:
        raise HTTPException(status_code=404, detail="Ambulance not found")

    hospitals = await db["hospitals"].find().to_list(length=None)
    status_documents = await db["hospital_status"].find().to_list(length=None)
    hospital_statuses = {doc["hospital_id"]: doc for doc in status_documents}

    result = await recommend_hospital(case, hospitals, hospital_statuses, ambulance["location"])

    recommendation_doc = {
        "case_id": case_id,
        "recommended_hospital_id": result.get("recommended_hospital_id"),
        "eta_minutes": result.get("eta_minutes"),
        "total_care_delay_minutes": result.get("total_care_delay_minutes"),
        "reasons": result.get("reasons", []),
        "alternatives": result.get("alternatives", []),
        "no_eligible_hospital": result.get("no_eligible_hospital", False),
        "created_at": datetime.now(timezone.utc),
    }
    await db["recommendations"].replace_one({"case_id": case_id}, recommendation_doc, upsert=True)

    await db["emergency_cases"].update_one(
        {"case_id": case_id}, {"$set": {"status": "RECOMMENDED"}}
    )

    stored = await db["recommendations"].find_one({"case_id": case_id})
    return _to_recommendation_response(stored)


@router.get("/recommendations/{case_id}", response_model=RecommendationResponse)
async def get_recommendation(
    case_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> RecommendationResponse:
    """Fetch the stored recommendation for an emergency case."""
    document = await db["recommendations"].find_one({"case_id": case_id})
    if document is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return _to_recommendation_response(document)


@router.post("/recommendations/{case_id}/accept")
async def accept_recommendation(
    case_id: str,
    payload: AcceptBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict:
    """Accept a hospital for a case.

    The ambulance crew usually accepts the recommended hospital but may pick any
    alternative that was part of the recommendation. Moves the case to `ACCEPTED`
    and records which hospital was actually chosen.
    """
    case = await db["emergency_cases"].find_one({"case_id": case_id})
    if case is None:
        raise HTTPException(status_code=404, detail="Emergency case not found")
    if await db["recommendations"].find_one({"case_id": case_id}) is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    if await db["hospitals"].find_one({"_id": payload.hospital_id}) is None:
        raise HTTPException(status_code=404, detail="Hospital not found")

    hospital_id = str(payload.hospital_id)
    await db["emergency_cases"].update_one(
        {"case_id": case_id},
        {"$set": {"status": "ACCEPTED", "accepted_hospital_id": hospital_id}},
    )
    await db["ambulances"].update_one(
        {"ambulance_id": case["ambulance_id"]}, {"$set": {"status": "BUSY"}}
    )
    return {
        "case_id": case_id,
        "status": "ACCEPTED",
        "accepted_hospital_id": hospital_id,
    }


@router.post("/emergencies/{case_id}/close", response_model=EmergencyCaseInDB)
async def close_emergency_case(
    case_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> EmergencyCaseInDB:
    """Close an emergency case and release its ambulance.

    Marks the case `CLOSED` (patient admitted / handover complete) and returns
    the assigned ambulance to `ACTIVE` so it can take the next call.
    """
    case = await db["emergency_cases"].find_one({"case_id": case_id})
    if case is None:
        raise HTTPException(status_code=404, detail="Emergency case not found")

    await db["emergency_cases"].update_one(
        {"case_id": case_id}, {"$set": {"status": "CLOSED"}}
    )
    await db["ambulances"].update_one(
        {"ambulance_id": case["ambulance_id"]}, {"$set": {"status": "ACTIVE"}}
    )
    saved = await db["emergency_cases"].find_one({"case_id": case_id})
    return EmergencyCaseInDB(**saved)
