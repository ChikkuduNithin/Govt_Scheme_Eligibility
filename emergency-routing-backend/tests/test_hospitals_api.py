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
MISSING_ID = ObjectId("6571a1a1a1a1a1a1a1a1a0ff")

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


def status_payload(hid, **overrides):
    payload = status_doc(hid, **overrides)
    payload.pop("updated_at")
    return payload


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
            await db["hospitals"].delete_many({})
            await db["hospital_status"].delete_many({})
            await db["hospitals"].insert_one(
                hospital_doc(HOSPITAL_A_ID, "Hospital A", {"lat": 17.42, "lng": 78.46})
            )
            await db["hospitals"].insert_one(
                hospital_doc(HOSPITAL_B_ID, "Hospital B", {"lat": 17.44, "lng": 78.48})
            )
            await db["hospital_status"].insert_one(status_doc(HOSPITAL_A_ID))
            return await scenario(db)
        finally:
            app.dependency_overrides.clear()

    try:
        return asyncio.run(_inner())
    finally:
        client.close()


def test_list_hospitals():
    async def scenario(db):
        response = await _request("GET", "/api/v1/hospitals")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert {h["name"] for h in data} == {"Hospital A", "Hospital B"}
        assert all("_id" in h for h in data)

    _run(scenario)


def test_list_hospitals_nearby_filter():
    async def scenario(db):
        near = await _request(
            "GET",
            "/api/v1/hospitals",
            params={"lat": 17.42, "lng": 78.46, "radius_km": 1.0},
        )
        assert near.status_code == 200
        data = near.json()
        assert len(data) == 1
        assert data[0]["name"] == "Hospital A"

        wide = await _request(
            "GET",
            "/api/v1/hospitals",
            params={"lat": 17.42, "lng": 78.46, "radius_km": 10.0},
        )
        assert wide.status_code == 200
        assert len(wide.json()) == 2

        partial = await _request("GET", "/api/v1/hospitals", params={"lat": 17.42})
        assert partial.status_code == 422

    _run(scenario)


def test_get_hospital_with_status():
    async def scenario(db):
        response = await _request("GET", f"/api/v1/hospitals/{HOSPITAL_A_ID}")
        assert response.status_code == 200
        data = response.json()
        assert data["_id"] == str(HOSPITAL_A_ID)
        assert data["name"] == "Hospital A"
        assert data["status"]["hospital_id"] == str(HOSPITAL_A_ID)
        assert data["status"]["icu_available"] == 5

    _run(scenario)


def test_get_hospital_without_status():
    async def scenario(db):
        response = await _request("GET", f"/api/v1/hospitals/{HOSPITAL_B_ID}")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Hospital B"
        assert data["status"] is None

    _run(scenario)


def test_get_hospital_not_found():
    async def scenario(db):
        response = await _request("GET", f"/api/v1/hospitals/{MISSING_ID}")
        assert response.status_code == 404
        assert response.json()["detail"] == "Hospital not found"

    _run(scenario)


def test_get_hospital_invalid_id_returns_422():
    async def scenario(db):
        response = await _request("GET", "/api/v1/hospitals/not-an-objectid")
        assert response.status_code == 422

    _run(scenario)


def test_get_hospital_status():
    async def scenario(db):
        response = await _request("GET", f"/api/v1/hospitals/{HOSPITAL_A_ID}/status")
        assert response.status_code == 200
        data = response.json()
        assert data["hospital_id"] == str(HOSPITAL_A_ID)
        assert data["icu_available"] == 5
        assert data["trauma_status"] == "AVAILABLE"

    _run(scenario)


def test_get_hospital_status_missing_returns_404():
    async def scenario(db):
        response = await _request("GET", f"/api/v1/hospitals/{HOSPITAL_B_ID}/status")
        assert response.status_code == 404
        assert response.json()["detail"] == "Hospital status not found"

    _run(scenario)


def test_upsert_status_updates_existing():
    async def scenario(db):
        payload = status_payload(
            HOSPITAL_A_ID,
            icu_available=1,
            trauma_status="UNAVAILABLE",
            accepting_patients=False,
        )
        response = await _request(
            "POST",
            f"/api/v1/hospitals/{HOSPITAL_A_ID}/status",
            json=payload,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["hospital_id"] == str(HOSPITAL_A_ID)
        assert data["icu_available"] == 1
        assert data["trauma_status"] == "UNAVAILABLE"
        assert data["accepting_patients"] is False
        assert data["updated_at"] is not None

        fetched = await _request("GET", f"/api/v1/hospitals/{HOSPITAL_A_ID}/status")
        assert fetched.json()["icu_available"] == 1

    _run(scenario)


def test_upsert_status_creates_new_status():
    async def scenario(db):
        payload = status_payload(HOSPITAL_B_ID, icu_available=2)
        response = await _request(
            "POST",
            f"/api/v1/hospitals/{HOSPITAL_B_ID}/status",
            json=payload,
        )
        assert response.status_code == 200
        assert response.json()["icu_available"] == 2

        fetched = await _request("GET", f"/api/v1/hospitals/{HOSPITAL_B_ID}/status")
        assert fetched.status_code == 200

    _run(scenario)


def test_upsert_status_unknown_hospital_returns_404():
    async def scenario(db):
        payload = status_payload(MISSING_ID)
        response = await _request(
            "POST",
            f"/api/v1/hospitals/{MISSING_ID}/status",
            json=payload,
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Hospital not found"

    _run(scenario)


def test_upsert_status_invalid_body_returns_422():
    async def scenario(db):
        payload = status_payload(HOSPITAL_A_ID)
        payload["trauma_status"] = "MAYBE"
        response = await _request(
            "POST",
            f"/api/v1/hospitals/{HOSPITAL_A_ID}/status",
            json=payload,
        )
        assert response.status_code == 422

    _run(scenario)
