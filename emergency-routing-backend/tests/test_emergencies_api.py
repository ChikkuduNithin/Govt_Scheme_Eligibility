import asyncio
from datetime import datetime, timezone

from bson import ObjectId
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.core.database import get_db
from app.main import app

TEST_DB_NAME = "emergency_routing_test"
BASE_URL = "http://test"

HOSPITAL_A_ID = ObjectId("6571a1a1a1a1a1a1a1a1a001")
HOSPITAL_B_ID = ObjectId("6571a1a1a1a1a1a1a1a1a002")
MISSING_HOSPITAL_ID = ObjectId("6571a1a1a1a1a1a1a1a1a0ff")
AMBULANCE_ID = ObjectId("6571b1b1b1b1b1b1b1b1b001")

FULL_CAPS = {
    "emergency": True,
    "trauma": True,
    "icu": True,
    "cardiology": True,
    "neurology": True,
    "ct": True,
    "cath_lab": True,
    "blood_bank": True,
    "surgery": True,
    "pediatrics": True,
    "obstetrics": True,
}

CASE_BODY = {
    "emergency_type": "TRAUMA",
    "severity": "HIGH",
    "patient": {
        "age": 45,
        "conscious": True,
        "spo2": 92,
        "heart_rate": 110,
        "bp": "130/85",
    },
    "ambulance_id": "amb-001",
}


def hospital_doc(hid, name, location):
    return {
        "_id": hid,
        "name": name,
        "location": location,
        "capabilities": dict(FULL_CAPS),
        "created_at": datetime.now(timezone.utc),
    }


def status_doc(hid, **overrides):
    doc = {
        "hospital_id": str(hid),
        "icu_available": 5,
        "icu_total": 10,
        "emergency_beds_available": 3,
        "emergency_beds_total": 8,
        "trauma_status": "AVAILABLE",
        "cardiology_status": "AVAILABLE",
        "neurology_status": "AVAILABLE",
        "ct_status": "AVAILABLE",
        "cath_lab_status": "AVAILABLE",
        "accepting_patients": True,
        "updated_at": datetime.now(timezone.utc),
    }
    doc.update(overrides)
    return doc


def ambulance_doc(hid, ambulance_id, location):
    return {
        "_id": hid,
        "ambulance_id": ambulance_id,
        "location": location,
        "type": "ALS",
        "status": "ACTIVE",
    }


async def _request(method, path, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
        return await client.request(method, path, **kwargs)


def _run(scenario):
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[TEST_DB_NAME]

    async def _inner():
        app.dependency_overrides[get_db] = lambda: db
        try:
            for collection in ("emergency_cases", "recommendations", "hospitals", "hospital_status", "ambulances"):
                await db[collection].delete_many({})
            return await scenario(db)
        finally:
            app.dependency_overrides.clear()

    try:
        return asyncio.run(_inner())
    finally:
        client.close()


async def _seed_standard(db):
    await db["hospitals"].insert_one(
        hospital_doc(HOSPITAL_A_ID, "Hospital A", {"lat": 17.42, "lng": 78.46})
    )
    await db["hospital_status"].insert_one(status_doc(HOSPITAL_A_ID))
    await db["ambulances"].insert_one(
        ambulance_doc(AMBULANCE_ID, "amb-001", {"lat": 17.40, "lng": 78.45})
    )


async def _create_case():
    response = await _request("POST", "/api/v1/emergencies", json=CASE_BODY)
    return response


def test_full_flow_create_recommend_accept(monkeypatch):
    monkeypatch.setattr(settings, "AVG_URBAN_SPEED_KMH", 30.0)

    async def scenario(db):
        await _seed_standard(db)
        created = await _create_case()
        assert created.status_code == 201
        case = created.json()
        case_id = case["case_id"]
        assert case["status"] == "OPEN"
        assert case["emergency_type"] == "TRAUMA"
        assert case["ambulance_id"] == "amb-001"
        assert case["created_at"]

        fetched = await _request("GET", f"/api/v1/emergencies/{case_id}")
        assert fetched.status_code == 200
        assert fetched.json()["case_id"] == case_id

        rec = await _request("POST", f"/api/v1/emergencies/{case_id}/recommend")
        assert rec.status_code == 200
        data = rec.json()
        assert data["case_id"] == case_id
        assert data["recommended_hospital_id"] == str(HOSPITAL_A_ID)
        assert data["eta_minutes"] is not None
        assert data["total_care_delay_minutes"] is not None
        assert any(r.startswith("ETA:") for r in data["reasons"])
        assert data["alternatives"] == []
        assert data["no_eligible_hospital"] is False
        assert data["created_at"]

        stored = await _request("GET", f"/api/v1/recommendations/{case_id}")
        assert stored.status_code == 200
        assert stored.json()["recommended_hospital_id"] == str(HOSPITAL_A_ID)

        case_after = (await _request("GET", f"/api/v1/emergencies/{case_id}")).json()
        assert case_after["status"] == "RECOMMENDED"

        accepted = await _request(
            "POST",
            f"/api/v1/recommendations/{case_id}/accept",
            json={"hospital_id": str(HOSPITAL_A_ID)},
        )
        assert accepted.status_code == 200
        payload = accepted.json()
        assert payload["case_id"] == case_id
        assert payload["status"] == "ACCEPTED"
        assert payload["accepted_hospital_id"] == str(HOSPITAL_A_ID)

        raw = await db["emergency_cases"].find_one({"case_id": case_id})
        assert raw["status"] == "ACCEPTED"
        assert raw["accepted_hospital_id"] == str(HOSPITAL_A_ID)

        ambulance = await db["ambulances"].find_one({"ambulance_id": "amb-001"})
        assert ambulance["status"] == "BUSY"

    _run(scenario)


def test_accept_alternative_hospital(monkeypatch):
    monkeypatch.setattr(settings, "AVG_URBAN_SPEED_KMH", 30.0)

    async def scenario(db):
        await db["hospitals"].insert_one(
            hospital_doc(HOSPITAL_A_ID, "Hospital A", {"lat": 17.42, "lng": 78.46})
        )
        await db["hospitals"].insert_one(
            hospital_doc(HOSPITAL_B_ID, "Hospital B", {"lat": 17.44, "lng": 78.48})
        )
        await db["hospital_status"].insert_one(status_doc(HOSPITAL_A_ID))
        await db["hospital_status"].insert_one(status_doc(HOSPITAL_B_ID))
        await db["ambulances"].insert_one(
            ambulance_doc(AMBULANCE_ID, "amb-001", {"lat": 17.40, "lng": 78.45})
        )

        case_id = (await _create_case()).json()["case_id"]
        rec = await _request("POST", f"/api/v1/emergencies/{case_id}/recommend")
        assert rec.json()["recommended_hospital_id"] == str(HOSPITAL_A_ID)
        alternative = [a for a in rec.json()["alternatives"] if a["hospital_id"] == str(HOSPITAL_B_ID)]
        assert alternative and alternative[0]["eliminated_reason"] is None

        accepted = await _request(
            "POST",
            f"/api/v1/recommendations/{case_id}/accept",
            json={"hospital_id": str(HOSPITAL_B_ID)},
        )
        assert accepted.status_code == 200
        assert accepted.json()["accepted_hospital_id"] == str(HOSPITAL_B_ID)

    _run(scenario)


def test_create_case_validation_error():
    async def scenario(db):
        bad = {**CASE_BODY, "severity": "URGENT"}
        response = await _request("POST", "/api/v1/emergencies", json=bad)
        assert response.status_code == 422

    _run(scenario)


def test_create_case_invalid_patient_bounds_returns_422():
    async def scenario(db):
        bad_patient = {**CASE_BODY["patient"], "spo2": 150, "heart_rate": 400, "age": -1}
        response = await _request(
            "POST", "/api/v1/emergencies", json={**CASE_BODY, "patient": bad_patient}
        )
        assert response.status_code == 422

    _run(scenario)


def test_create_case_invalid_bp_format_returns_422():
    async def scenario(db):
        bad_patient = {**CASE_BODY["patient"], "bp": "one-twenty-over-eighty"}
        response = await _request(
            "POST", "/api/v1/emergencies", json={**CASE_BODY, "patient": bad_patient}
        )
        assert response.status_code == 422

    _run(scenario)


def test_get_case_not_found():
    async def scenario(db):
        response = await _request("GET", "/api/v1/emergencies/case-does-not-exist")
        assert response.status_code == 404
        assert response.json()["detail"] == "Emergency case not found"

    _run(scenario)


def test_recommend_case_not_found():
    async def scenario(db):
        response = await _request("POST", "/api/v1/emergencies/case-does-not-exist/recommend")
        assert response.status_code == 404

    _run(scenario)


def test_recommend_ambulance_not_found(monkeypatch):
    monkeypatch.setattr(settings, "AVG_URBAN_SPEED_KMH", 30.0)

    async def scenario(db):
        await _seed_standard(db)
        case_id = (await _create_case()).json()["case_id"]
        await db["emergency_cases"].update_one(
            {"case_id": case_id}, {"$set": {"ambulance_id": "amb-missing"}}
        )
        response = await _request("POST", f"/api/v1/emergencies/{case_id}/recommend")
        assert response.status_code == 404
        assert response.json()["detail"] == "Ambulance not found"

    _run(scenario)


def test_recommend_no_eligible_hospital(monkeypatch):
    monkeypatch.setattr(settings, "AVG_URBAN_SPEED_KMH", 30.0)

    async def scenario(db):
        await db["hospitals"].insert_one(
            hospital_doc(HOSPITAL_A_ID, "Hospital A", {"lat": 17.42, "lng": 78.46})
        )
        await db["hospital_status"].insert_one(
            status_doc(HOSPITAL_A_ID, accepting_patients=False)
        )
        await db["ambulances"].insert_one(
            ambulance_doc(AMBULANCE_ID, "amb-001", {"lat": 17.40, "lng": 78.45})
        )

        case_id = (await _create_case()).json()["case_id"]
        response = await _request("POST", f"/api/v1/emergencies/{case_id}/recommend")
        assert response.status_code == 200
        data = response.json()
        assert data["no_eligible_hospital"] is True
        assert data["recommended_hospital_id"] is None
        reasons = {a["hospital_id"]: a["eliminated_reason"] for a in data["alternatives"]}
        assert reasons[str(HOSPITAL_A_ID)] == "Hospital not accepting patients"

        stored = await _request("GET", f"/api/v1/recommendations/{case_id}")
        assert stored.json()["no_eligible_hospital"] is True

    _run(scenario)


def test_get_recommendation_not_found():
    async def scenario(db):
        response = await _request("GET", "/api/v1/recommendations/case-does-not-exist")
        assert response.status_code == 404
        assert response.json()["detail"] == "Recommendation not found"

    _run(scenario)


def test_accept_without_recommendation_returns_404():
    async def scenario(db):
        await _seed_standard(db)
        case_id = (await _create_case()).json()["case_id"]
        response = await _request(
            "POST",
            f"/api/v1/recommendations/{case_id}/accept",
            json={"hospital_id": str(HOSPITAL_A_ID)},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Recommendation not found"

    _run(scenario)


def test_accept_unknown_case_returns_404():
    async def scenario(db):
        response = await _request(
            "POST",
            "/api/v1/recommendations/case-does-not-exist/accept",
            json={"hospital_id": str(HOSPITAL_A_ID)},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Emergency case not found"

    _run(scenario)


def test_accept_unknown_hospital_returns_404(monkeypatch):
    monkeypatch.setattr(settings, "AVG_URBAN_SPEED_KMH", 30.0)

    async def scenario(db):
        await _seed_standard(db)
        case_id = (await _create_case()).json()["case_id"]
        await _request("POST", f"/api/v1/emergencies/{case_id}/recommend")
        response = await _request(
            "POST",
            f"/api/v1/recommendations/{case_id}/accept",
            json={"hospital_id": str(MISSING_HOSPITAL_ID)},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Hospital not found"

    _run(scenario)


def test_accept_invalid_hospital_id_returns_422(monkeypatch):
    monkeypatch.setattr(settings, "AVG_URBAN_SPEED_KMH", 30.0)

    async def scenario(db):
        await _seed_standard(db)
        case_id = (await _create_case()).json()["case_id"]
        await _request("POST", f"/api/v1/emergencies/{case_id}/recommend")
        response = await _request(
            "POST",
            f"/api/v1/recommendations/{case_id}/accept",
            json={"hospital_id": "not-an-objectid"},
        )
        assert response.status_code == 422

    _run(scenario)


def test_close_case_releases_ambulance(monkeypatch):
    monkeypatch.setattr(settings, "AVG_URBAN_SPEED_KMH", 30.0)

    async def scenario(db):
        await _seed_standard(db)
        case_id = (await _create_case()).json()["case_id"]
        await _request("POST", f"/api/v1/emergencies/{case_id}/recommend")
        await _request(
            "POST",
            f"/api/v1/recommendations/{case_id}/accept",
            json={"hospital_id": str(HOSPITAL_A_ID)},
        )
        assert (await db["ambulances"].find_one({"ambulance_id": "amb-001"}))["status"] == "BUSY"

        closed = await _request("POST", f"/api/v1/emergencies/{case_id}/close")
        assert closed.status_code == 200
        assert closed.json()["status"] == "CLOSED"

        raw = await db["emergency_cases"].find_one({"case_id": case_id})
        assert raw["status"] == "CLOSED"
        assert (await db["ambulances"].find_one({"ambulance_id": "amb-001"}))["status"] == "ACTIVE"

    _run(scenario)


def test_close_case_not_found_returns_404():
    async def scenario(db):
        response = await _request("POST", "/api/v1/emergencies/case-missing/close")
        assert response.status_code == 404
        assert response.json()["detail"] == "Emergency case not found"

    _run(scenario)
