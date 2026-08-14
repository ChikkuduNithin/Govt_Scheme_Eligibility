import asyncio
import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.core.database import get_db
from app.models.emergency_case import EmergencyType, PatientInfo
from app.models.py_object_id import PyObjectId
from app.services.clinical_requirements import get_required_capabilities
from app.services.decision_engine import recommend_hospital
from app.services.ws_manager import manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["alerts"])


class HospitalAlertRequest(BaseModel):
    case_id: str
    hospital_id: PyObjectId


class AlertSnapshot(BaseModel):
    patient: PatientInfo
    emergency_type: EmergencyType
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    required_capabilities: dict[str, str | bool]
    eta_minutes: float | None = None


class HospitalAlertResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: PyObjectId = Field(alias="_id")
    case_id: str
    hospital_id: str
    status: Literal["PENDING", "ACCEPTED", "REJECTED"]
    snapshot: AlertSnapshot
    created_at: datetime


async def _load_alert_or_404(
    db: AsyncIOMotorDatabase, alert_id: PyObjectId
) -> dict:
    document = await db["hospital_alerts"].find_one({"_id": alert_id})
    if document is None:
        raise HTTPException(status_code=404, detail="Hospital alert not found")
    return document


def _to_ws_message(document: dict) -> dict:
    return {
        "id": str(document["_id"]),
        "case_id": document["case_id"],
        "hospital_id": document["hospital_id"],
        "status": document["status"],
        "snapshot": document["snapshot"],
        "created_at": document["created_at"].isoformat(),
    }


async def _reroute_after_rejection(db: AsyncIOMotorDatabase, alert: dict) -> None:
    """Re-run the decision engine excluding a rejected hospital.

    Stores a fresh recommendation and broadcasts it over WebSocket to the
    ambulance's channel. Shared by the manual reject endpoint and the automatic
    alert-response timeout.
    """
    case = await db["emergency_cases"].find_one({"case_id": alert["case_id"]})
    ambulance = await db["ambulances"].find_one(
        {"ambulance_id": case["ambulance_id"]}
    )
    if ambulance is None:
        raise HTTPException(status_code=404, detail="Ambulance not found")

    hospitals = await db["hospitals"].find().to_list(length=None)
    hospitals = [h for h in hospitals if str(h["_id"]) != alert["hospital_id"]]
    status_documents = await db["hospital_status"].find().to_list(length=None)
    hospital_statuses = {doc["hospital_id"]: doc for doc in status_documents}

    result = await recommend_hospital(case, hospitals, hospital_statuses, ambulance["location"])

    recommendation_doc = {
        "case_id": alert["case_id"],
        "recommended_hospital_id": result.get("recommended_hospital_id"),
        "eta_minutes": result.get("eta_minutes"),
        "total_care_delay_minutes": result.get("total_care_delay_minutes"),
        "reasons": result.get("reasons", []),
        "alternatives": result.get("alternatives", []),
        "no_eligible_hospital": result.get("no_eligible_hospital", False),
        "created_at": datetime.now(timezone.utc),
    }
    await db["recommendations"].replace_one(
        {"case_id": alert["case_id"]}, recommendation_doc, upsert=True
    )

    await manager.broadcast_to_key(
        ambulance["ambulance_id"],
        {
            "case_id": alert["case_id"],
            "recommended_hospital_id": recommendation_doc["recommended_hospital_id"],
            "eta_minutes": recommendation_doc["eta_minutes"],
            "total_care_delay_minutes": recommendation_doc["total_care_delay_minutes"],
            "reasons": recommendation_doc["reasons"],
            "alternatives": recommendation_doc["alternatives"],
            "no_eligible_hospital": recommendation_doc["no_eligible_hospital"],
            "created_at": recommendation_doc["created_at"].isoformat(),
        },
    )


async def _alert_timeout(db: AsyncIOMotorDatabase, alert_id: PyObjectId) -> None:
    """Background task: auto-reject + re-route a PENDING alert that got no response."""
    await asyncio.sleep(settings.ALERT_RESPONSE_TIMEOUT_SECONDS)
    try:
        alert = await db["hospital_alerts"].find_one({"_id": alert_id})
        if alert is None or alert.get("status") != "PENDING":
            return
        await db["hospital_alerts"].update_one(
            {"_id": alert_id}, {"$set": {"status": "REJECTED"}}
        )
        alert = await db["hospital_alerts"].find_one({"_id": alert_id})
        await _reroute_after_rejection(db, alert)
    except Exception:
        logger.exception("Background alert timeout failed for alert %s", alert_id)


@router.post("/hospital-alerts", response_model=HospitalAlertResponse, status_code=201)
async def create_hospital_alert(
    payload: HospitalAlertRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> HospitalAlertResponse:
    """Notify a hospital about an emergency case.

    Creates a `hospital_alerts` document in status `PENDING` embedding a
    snapshot of the case (patient info, emergency type, required capabilities
    and ETA from the stored recommendation), then broadcasts it over WebSocket
    to the hospital's dashboard channel.

    If the hospital does not respond within `ALERT_RESPONSE_TIMEOUT_SECONDS`,
    a background task auto-rejects the alert and re-routes the case.
    """
    case = await db["emergency_cases"].find_one({"case_id": payload.case_id})
    if case is None:
        raise HTTPException(status_code=404, detail="Emergency case not found")
    if await db["hospitals"].find_one({"_id": payload.hospital_id}) is None:
        raise HTTPException(status_code=404, detail="Hospital not found")
    recommendation = await db["recommendations"].find_one(
        {"case_id": payload.case_id}
    )
    if recommendation is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")

    required_capabilities = get_required_capabilities(
        case["emergency_type"], case["severity"]
    )
    alert_doc = {
        "case_id": payload.case_id,
        "hospital_id": str(payload.hospital_id),
        "status": "PENDING",
        "snapshot": {
            "patient": case["patient"],
            "emergency_type": case["emergency_type"],
            "severity": case["severity"],
            "required_capabilities": required_capabilities,
            "eta_minutes": recommendation.get("eta_minutes"),
        },
        "created_at": datetime.now(timezone.utc),
    }
    inserted = await db["hospital_alerts"].insert_one(alert_doc)
    saved = await db["hospital_alerts"].find_one({"_id": inserted.inserted_id})

    await manager.broadcast_to_key(saved["hospital_id"], _to_ws_message(saved))
    asyncio.create_task(_alert_timeout(db, saved["_id"]))
    return HospitalAlertResponse(**saved)


@router.post("/hospital-alerts/{alert_id}/accept", response_model=HospitalAlertResponse)
async def accept_hospital_alert(
    alert_id: PyObjectId,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> HospitalAlertResponse:
    """Mark a hospital alert as accepted by the hospital."""
    await _load_alert_or_404(db, alert_id)
    await db["hospital_alerts"].update_one(
        {"_id": alert_id}, {"$set": {"status": "ACCEPTED"}}
    )
    saved = await db["hospital_alerts"].find_one({"_id": alert_id})
    return HospitalAlertResponse(**saved)


@router.post("/hospital-alerts/{alert_id}/reject", response_model=HospitalAlertResponse)
async def reject_hospital_alert(
    alert_id: PyObjectId,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> HospitalAlertResponse:
    """Mark a hospital alert as rejected and re-route the case.

    Marks the alert `REJECTED`, then re-runs the decision engine excluding the
    rejected hospital, stores a new recommendation and broadcasts it over
    WebSocket to the ambulance's channel.
    """
    await _load_alert_or_404(db, alert_id)
    await db["hospital_alerts"].update_one(
        {"_id": alert_id}, {"$set": {"status": "REJECTED"}}
    )

    alert = await db["hospital_alerts"].find_one({"_id": alert_id})
    await _reroute_after_rejection(db, alert)
    return HospitalAlertResponse(**alert)
