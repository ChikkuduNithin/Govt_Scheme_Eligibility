import asyncio

from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.core.database import get_db
from app.main import app

TEST_DB_NAME = "emergency_routing_test"
BASE_URL = "http://test"

AMBULANCE_BODY = {
    "ambulance_id": "amb-010",
    "location": {"lat": 17.40, "lng": 78.45},
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
            await db["ambulances"].delete_many({})
            return await scenario(db)
        finally:
            app.dependency_overrides.clear()

    try:
        return asyncio.run(_inner())
    finally:
        client.close()


def test_register_ambulance():
    async def scenario(db):
        response = await _request("POST", "/api/v1/ambulances", json=AMBULANCE_BODY)
        assert response.status_code == 201
        data = response.json()
        assert data["ambulance_id"] == "amb-010"
        assert data["status"] == "ACTIVE"
        assert data["location"]["lat"] == 17.40
        assert data["_id"]

    _run(scenario)


def test_register_duplicate_ambulance_returns_409():
    async def scenario(db):
        await _request("POST", "/api/v1/ambulances", json=AMBULANCE_BODY)
        response = await _request("POST", "/api/v1/ambulances", json=AMBULANCE_BODY)
        assert response.status_code == 409
        assert response.json()["detail"] == "Ambulance already registered"

    _run(scenario)


def test_register_invalid_status_returns_422():
    async def scenario(db):
        body = {**AMBULANCE_BODY, "status": "IN_FLIGHT"}
        response = await _request("POST", "/api/v1/ambulances", json=body)
        assert response.status_code == 422

    _run(scenario)


def test_list_ambulances_and_filter_by_status():
    async def scenario(db):
        await _request("POST", "/api/v1/ambulances", json=AMBULANCE_BODY)
        await _request(
            "POST",
            "/api/v1/ambulances",
            json={**AMBULANCE_BODY, "ambulance_id": "amb-011", "status": "BUSY"},
        )
        all_response = await _request("GET", "/api/v1/ambulances")
        assert all_response.status_code == 200
        assert [a["ambulance_id"] for a in all_response.json()] == ["amb-010", "amb-011"]

        busy = await _request("GET", "/api/v1/ambulances?status=BUSY")
        assert [a["ambulance_id"] for a in busy.json()] == ["amb-011"]

    _run(scenario)


def test_list_ambulances_nearby():
    async def scenario(db):
        await _request("POST", "/api/v1/ambulances", json=AMBULANCE_BODY)
        await _request(
            "POST",
            "/api/v1/ambulances",
            json={
                **AMBULANCE_BODY,
                "ambulance_id": "amb-012",
                "location": {"lat": 17.90, "lng": 79.10},
            },
        )
        response = await _request(
            "GET", "/api/v1/ambulances?lat=17.40&lng=78.45&radius_km=10"
        )
        assert [a["ambulance_id"] for a in response.json()] == ["amb-010"]

    _run(scenario)


def test_list_ambulances_partial_radius_params_returns_422():
    async def scenario(db):
        response = await _request("GET", "/api/v1/ambulances?lat=17.40&lng=78.45")
        assert response.status_code == 422

    _run(scenario)


def test_get_ambulance():
    async def scenario(db):
        await _request("POST", "/api/v1/ambulances", json=AMBULANCE_BODY)
        response = await _request("GET", "/api/v1/ambulances/amb-010")
        assert response.status_code == 200
        assert response.json()["ambulance_id"] == "amb-010"

    _run(scenario)


def test_get_ambulance_not_found_returns_404():
    async def scenario(db):
        response = await _request("GET", "/api/v1/ambulances/amb-missing")
        assert response.status_code == 404
        assert response.json()["detail"] == "Ambulance not found"

    _run(scenario)


def test_update_location_and_status():
    async def scenario(db):
        await _request("POST", "/api/v1/ambulances", json=AMBULANCE_BODY)

        location = await _request(
            "PATCH",
            "/api/v1/ambulances/amb-010",
            json={"location": {"lat": 17.50, "lng": 78.60}},
        )
        assert location.status_code == 200
        assert location.json()["location"] == {"lat": 17.50, "lng": 78.60}

        status = await _request(
            "PATCH", "/api/v1/ambulances/amb-010", json={"status": "BUSY"}
        )
        assert status.status_code == 200
        assert status.json()["status"] == "BUSY"

        raw = await db["ambulances"].find_one({"ambulance_id": "amb-010"})
        assert raw["location"] == {"lat": 17.50, "lng": 78.60}
        assert raw["status"] == "BUSY"

    _run(scenario)


def test_update_ambulance_not_found_returns_404():
    async def scenario(db):
        response = await _request(
            "PATCH", "/api/v1/ambulances/amb-missing", json={"status": "BUSY"}
        )
        assert response.status_code == 404

    _run(scenario)


def test_update_empty_body_returns_422():
    async def scenario(db):
        await _request("POST", "/api/v1/ambulances", json=AMBULANCE_BODY)
        response = await _request("PATCH", "/api/v1/ambulances/amb-010", json={})
        assert response.status_code == 422

    _run(scenario)
