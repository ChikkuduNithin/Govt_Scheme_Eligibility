import asyncio
import time
from datetime import datetime, timezone

from bson import ObjectId
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.core.database import get_db
from app.main import app

TEST_DB_NAME = "emergency_routing_test"
BASE_URL = "http://test"

HOSPITAL_A_ID = ObjectId("6571a1a1a1a1a1a1a1a1a001")
HOSPITAL_B_ID = ObjectId("6571a1a1a1a1a1a1a1a1a002")
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


def alert_body(case_id, hospital_id):
    return {"case_id": case_id, "hospital_id": str(hospital_id)}


async def _request(method, path, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
        return await client.request(method, path, **kwargs)


async def _seed_standard(db):
    await db["hospitals"].insert_one(
        hospital_doc(HOSPITAL_A_ID, "Hospital A", {"lat": 17.42, "lng": 78.46})
    )
    await db["hospital_status"].insert_one(status_doc(HOSPITAL_A_ID))
    await db["ambulances"].insert_one(
        ambulance_doc(AMBULANCE_ID, "amb-001", {"lat": 17.40, "lng": 78.45})
    )


async def _seed_two_hospitals(db):
    await _seed_standard(db)
    await db["hospitals"].insert_one(
        hospital_doc(HOSPITAL_B_ID, "Hospital B", {"lat": 17.44, "lng": 78.48})
    )
    await db["hospital_status"].insert_one(status_doc(HOSPITAL_B_ID))


async def _create_case_and_recommend():
    created = await _request("POST", "/api/v1/emergencies", json=CASE_BODY)
    case_id = created.json()["case_id"]
    rec = await _request("POST", f"/api/v1/emergencies/{case_id}/recommend")
    assert rec.status_code == 200
    return case_id, rec.json()


def _run(scenario):
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[TEST_DB_NAME]

    async def _inner():
        app.dependency_overrides[get_db] = lambda: db
        try:
            for collection in (
                "emergency_cases",
                "recommendations",
                "hospitals",
                "hospital_status",
                "ambulances",
                "hospital_alerts",
            ):
                await db[collection].delete_many({})
            return await scenario(db)
        finally:
            app.dependency_overrides.clear()

    try:
        return asyncio.run(_inner())
    finally:
        client.close()


def test_create_alert_pending_with_snapshot(monkeypatch):
    monkeypatch.setattr(settings, "AVG_URBAN_SPEED_KMH", 30.0)

    async def scenario(db):
        await _seed_standard(db)
        case_id, rec = await _create_case_and_recommend()

        response = await _request(
            "POST", "/api/v1/hospital-alerts", json=alert_body(case_id, HOSPITAL_A_ID)
        )
        assert response.status_code == 201
        data = response.json()
        assert data["case_id"] == case_id
        assert data["hospital_id"] == str(HOSPITAL_A_ID)
        assert data["status"] == "PENDING"
        assert data["_id"]
        assert data["created_at"]

        snapshot = data["snapshot"]
        assert snapshot["patient"]["age"] == 45
        assert snapshot["emergency_type"] == "TRAUMA"
        assert snapshot["required_capabilities"]["trauma"] is True
        assert snapshot["eta_minutes"] == rec["eta_minutes"]

        stored = await db["hospital_alerts"].find_one({"_id": ObjectId(data["_id"])})
        assert stored["status"] == "PENDING"

    _run(scenario)


def test_create_alert_unknown_case_returns_404():
    async def scenario(db):
        await _seed_standard(db)
        response = await _request(
            "POST",
            "/api/v1/hospital-alerts",
            json=alert_body("case-missing", HOSPITAL_A_ID),
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Emergency case not found"

    _run(scenario)


def test_create_alert_unknown_hospital_returns_404(monkeypatch):
    monkeypatch.setattr(settings, "AVG_URBAN_SPEED_KMH", 30.0)

    async def scenario(db):
        await _seed_standard(db)
        case_id, _ = await _create_case_and_recommend()
        missing = ObjectId("6571a1a1a1a1a1a1a1a1a0ff")
        response = await _request(
            "POST", "/api/v1/hospital-alerts", json=alert_body(case_id, missing)
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Hospital not found"

    _run(scenario)


def test_create_alert_without_recommendation_returns_404(monkeypatch):
    monkeypatch.setattr(settings, "AVG_URBAN_SPEED_KMH", 30.0)

    async def scenario(db):
        await _seed_standard(db)
        created = await _request("POST", "/api/v1/emergencies", json=CASE_BODY)
        case_id = created.json()["case_id"]
        response = await _request(
            "POST",
            "/api/v1/hospital-alerts",
            json=alert_body(case_id, HOSPITAL_A_ID),
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Recommendation not found"

    _run(scenario)


def test_accept_alert(monkeypatch):
    monkeypatch.setattr(settings, "AVG_URBAN_SPEED_KMH", 30.0)

    async def scenario(db):
        await _seed_standard(db)
        case_id, _ = await _create_case_and_recommend()
        alert_id = (
            await _request(
                "POST",
                "/api/v1/hospital-alerts",
                json=alert_body(case_id, HOSPITAL_A_ID),
            )
        ).json()["_id"]

        response = await _request(
            "POST", f"/api/v1/hospital-alerts/{alert_id}/accept"
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ACCEPTED"

        stored = await db["hospital_alerts"].find_one({"_id": ObjectId(alert_id)})
        assert stored["status"] == "ACCEPTED"

    _run(scenario)


def test_accept_alert_not_found_returns_404():
    async def scenario(db):
        missing = ObjectId("6571a1a1a1a1a1a1a1a1a0ff")
        response = await _request(
            "POST", f"/api/v1/hospital-alerts/{missing}/accept"
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Hospital alert not found"

    _run(scenario)


def test_accept_alert_invalid_id_returns_422():
    async def scenario(db):
        response = await _request(
            "POST", "/api/v1/hospital-alerts/not-an-objectid/accept"
        )
        assert response.status_code == 422

    _run(scenario)


def test_reject_reroutes_to_alternative(monkeypatch):
    monkeypatch.setattr(settings, "AVG_URBAN_SPEED_KMH", 30.0)

    async def scenario(db):
        await _seed_two_hospitals(db)
        case_id, rec = await _create_case_and_recommend()
        assert rec["recommended_hospital_id"] == str(HOSPITAL_A_ID)

        alert_id = (
            await _request(
                "POST",
                "/api/v1/hospital-alerts",
                json=alert_body(case_id, HOSPITAL_A_ID),
            )
        ).json()["_id"]

        response = await _request(
            "POST", f"/api/v1/hospital-alerts/{alert_id}/reject"
        )
        assert response.status_code == 200
        assert response.json()["status"] == "REJECTED"

        stored_rec = await db["recommendations"].find_one({"case_id": case_id})
        assert stored_rec["recommended_hospital_id"] == str(HOSPITAL_B_ID)
        assert stored_rec["eta_minutes"] is not None

        stored_alert = await db["hospital_alerts"].find_one({"_id": ObjectId(alert_id)})
        assert stored_alert["status"] == "REJECTED"

    _run(scenario)


def test_reject_alert_not_found_returns_404():
    async def scenario(db):
        missing = ObjectId("6571a1a1a1a1a1a1a1a1a0ff")
        response = await _request(
            "POST", f"/api/v1/hospital-alerts/{missing}/reject"
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Hospital alert not found"

    _run(scenario)


def _ws_test_setup(seed_two_hospitals=False):
    client = AsyncIOMotorClient(settings.MONGO_URI)

    async def _inner():
        db = client[TEST_DB_NAME]
        for collection in (
            "emergency_cases",
            "recommendations",
            "hospitals",
            "hospital_status",
            "ambulances",
            "hospital_alerts",
        ):
            await db[collection].delete_many({})
        await _seed_standard(db)
        if seed_two_hospitals:
            await db["hospitals"].insert_one(
                hospital_doc(HOSPITAL_B_ID, "Hospital B", {"lat": 17.44, "lng": 78.48})
            )
            await db["hospital_status"].insert_one(status_doc(HOSPITAL_B_ID))

    asyncio.run(_inner())
    client.close()
    app.dependency_overrides[get_db] = (
        lambda: AsyncIOMotorClient(settings.MONGO_URI)[TEST_DB_NAME]
    )
    return TestClient(app)


def test_ws_hospital_receives_alert(monkeypatch):
    monkeypatch.setattr(settings, "AVG_URBAN_SPEED_KMH", 30.0)
    client = _ws_test_setup()
    try:
        with client:
            created = client.post("/api/v1/emergencies", json=CASE_BODY)
            case_id = created.json()["case_id"]
            rec = client.post(f"/api/v1/emergencies/{case_id}/recommend")
            assert rec.status_code == 200

            with client.websocket_connect(f"/ws/hospital/{HOSPITAL_A_ID}") as ws:
                alert = client.post(
                    "/api/v1/hospital-alerts",
                    json=alert_body(case_id, HOSPITAL_A_ID),
                )
                assert alert.status_code == 201
                message = ws.receive_json()
                assert message["case_id"] == case_id
                assert message["hospital_id"] == str(HOSPITAL_A_ID)
                assert message["status"] == "PENDING"
                assert message["snapshot"]["emergency_type"] == "TRAUMA"
                assert message["snapshot"]["eta_minutes"] == rec.json()["eta_minutes"]
    finally:
        app.dependency_overrides.clear()


def test_ws_ambulance_receives_reroute(monkeypatch):
    monkeypatch.setattr(settings, "AVG_URBAN_SPEED_KMH", 30.0)
    client = _ws_test_setup(seed_two_hospitals=True)
    try:
        with client:
            created = client.post("/api/v1/emergencies", json=CASE_BODY)
            case_id = created.json()["case_id"]
            rec = client.post(f"/api/v1/emergencies/{case_id}/recommend")
            assert rec.status_code == 200
            assert rec.json()["recommended_hospital_id"] == str(HOSPITAL_A_ID)

            alert_id = client.post(
                "/api/v1/hospital-alerts",
                json=alert_body(case_id, HOSPITAL_A_ID),
            ).json()["_id"]

            with client.websocket_connect("/ws/ambulance/amb-001") as ws:
                rejected = client.post(
                    f"/api/v1/hospital-alerts/{alert_id}/reject"
                )
                assert rejected.status_code == 200
                assert rejected.json()["status"] == "REJECTED"

                message = ws.receive_json()
                assert message["case_id"] == case_id
                assert message["recommended_hospital_id"] == str(HOSPITAL_B_ID)
                assert message["eta_minutes"] is not None
                assert message["no_eligible_hospital"] is False
                assert message["created_at"]
    finally:
        app.dependency_overrides.clear()


def test_alert_auto_rejects_and_reroutes_after_timeout(monkeypatch):
    monkeypatch.setattr(settings, "AVG_URBAN_SPEED_KMH", 30.0)
    monkeypatch.setattr(settings, "ALERT_RESPONSE_TIMEOUT_SECONDS", 0.2)
    client = _ws_test_setup(seed_two_hospitals=True)
    case_id = None
    alert_id = None
    try:
        with client:
            created = client.post("/api/v1/emergencies", json=CASE_BODY)
            case_id = created.json()["case_id"]
            rec = client.post(f"/api/v1/emergencies/{case_id}/recommend")
            assert rec.json()["recommended_hospital_id"] == str(HOSPITAL_A_ID)

            with client.websocket_connect("/ws/ambulance/amb-001") as ws:
                alert = client.post(
                    "/api/v1/hospital-alerts",
                    json=alert_body(case_id, HOSPITAL_A_ID),
                )
                assert alert.status_code == 201
                alert_id = alert.json()["_id"]

                time.sleep(0.6)

                message = ws.receive_json()
                assert message["case_id"] == case_id
                assert message["recommended_hospital_id"] == str(HOSPITAL_B_ID)
    finally:
        app.dependency_overrides.clear()

    async def _check():
        checker = AsyncIOMotorClient(settings.MONGO_URI)
        try:
            db = checker[TEST_DB_NAME]
            stored_alert = await db["hospital_alerts"].find_one({"_id": ObjectId(alert_id)})
            stored_rec = await db["recommendations"].find_one({"case_id": case_id})
            return stored_alert, stored_rec
        finally:
            checker.close()

    stored_alert, stored_rec = asyncio.run(_check())
    assert stored_alert["status"] == "REJECTED"
    assert stored_rec["recommended_hospital_id"] == str(HOSPITAL_B_ID)


def test_alert_not_auto_rejected_when_accepted_before_timeout(monkeypatch):
    monkeypatch.setattr(settings, "AVG_URBAN_SPEED_KMH", 30.0)
    monkeypatch.setattr(settings, "ALERT_RESPONSE_TIMEOUT_SECONDS", 0.2)
    client = _ws_test_setup()
    case_id = None
    alert_id = None
    try:
        with client:
            created = client.post("/api/v1/emergencies", json=CASE_BODY)
            case_id = created.json()["case_id"]
            client.post(f"/api/v1/emergencies/{case_id}/recommend")
            alert = client.post(
                "/api/v1/hospital-alerts",
                json=alert_body(case_id, HOSPITAL_A_ID),
            )
            alert_id = alert.json()["_id"]
            accepted = client.post(f"/api/v1/hospital-alerts/{alert_id}/accept")
            assert accepted.status_code == 200

            time.sleep(0.6)
    finally:
        app.dependency_overrides.clear()

    async def _check():
        checker = AsyncIOMotorClient(settings.MONGO_URI)
        try:
            db = checker[TEST_DB_NAME]
            return await db["hospital_alerts"].find_one({"_id": ObjectId(alert_id)})
        finally:
            checker.close()

    stored_alert = asyncio.run(_check())
    assert stored_alert["status"] == "ACCEPTED"

