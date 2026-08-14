from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings

client: AsyncIOMotorClient | None = None


async def connect_to_mongo() -> None:
    global client
    if client is None:
        client = AsyncIOMotorClient(settings.MONGO_URI)
        await client.admin.command("ping")


async def close_mongo_connection() -> None:
    global client
    if client is not None:
        client.close()
        client = None


def get_db() -> AsyncIOMotorDatabase:
    if client is None:
        raise RuntimeError("MongoDB connection is not initialized")
    return client[settings.DB_NAME]


async def create_indexes(db: AsyncIOMotorDatabase) -> None:
    """Create the application's indexes. Idempotent, safe to run on every start."""
    await db["emergency_cases"].create_index("case_id", unique=True)
    await db["recommendations"].create_index("case_id", unique=True)
    await db["hospital_status"].create_index("hospital_id", unique=True)
    await db["ambulances"].create_index("ambulance_id", unique=True)
    await db["hospital_alerts"].create_index([("case_id", 1), ("hospital_id", 1)])
    await db["hospital_alerts"].create_index("status")
