import asyncio

from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.core.database import create_indexes

TEST_DB_NAME = "emergency_routing_test"

COLLECTIONS = (
    "emergency_cases",
    "recommendations",
    "hospital_status",
    "ambulances",
    "hospital_alerts",
)


def test_create_indexes_are_idempotent():
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[TEST_DB_NAME]

    async def _inner():
        for collection in COLLECTIONS:
            await db[collection].delete_many({})
        await create_indexes(db)
        await create_indexes(db)
        indexes = {}
        for collection in COLLECTIONS:
            info = await db[collection].index_information()
            indexes[collection] = {
                name: spec for name, spec in info.items() if name != "_id_"
            }
        for collection in COLLECTIONS:
            await db[collection].drop_indexes()
        return indexes

    indexes = asyncio.run(_inner())
    client.close()

    assert indexes["emergency_cases"]["case_id_1"]["unique"] is True
    assert indexes["recommendations"]["case_id_1"]["unique"] is True
    assert indexes["hospital_status"]["hospital_id_1"]["unique"] is True
    assert indexes["ambulances"]["ambulance_id_1"]["unique"] is True
    assert "case_id_1_hospital_id_1" in indexes["hospital_alerts"]
    assert "status_1" in indexes["hospital_alerts"]
