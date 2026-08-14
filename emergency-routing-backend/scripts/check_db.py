import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings


async def main() -> None:
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[settings.DB_NAME]
    try:
        await client.admin.command("ping")
        print(f"Connected to MongoDB at {settings.MONGO_URI}")
        print(f"Database: {settings.DB_NAME}")

        collections = await db.list_collection_names()
        print(f"Existing collections: {collections or '(none)'}")

        doc = {"name": "connection_test", "created_at": "throwaway"}
        inserted = await db["connection_test"].insert_one(doc)
        read_back = await db["connection_test"].find_one({"_id": inserted.inserted_id})
        print(f"Read back test document: {read_back}")

        await db["connection_test"].delete_one({"_id": inserted.inserted_id})
        print("Test document deleted.")

        print("SUCCESS: MongoDB connection and basic read/write/delete all work.")
    except Exception as exc:
        print(f"FAILURE: Could not verify MongoDB connection: {exc}")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
