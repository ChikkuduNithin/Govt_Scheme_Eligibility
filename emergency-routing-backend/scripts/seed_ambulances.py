import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.core.database import close_mongo_connection, connect_to_mongo, get_db
from app.models.ambulance import AmbulanceCreate

AMBULANCES = [
    {
        "ambulance_id": "amb-001",
        "location": {"lat": 17.4016, "lng": 78.4373},
        "type": "ALS",
        "status": "ACTIVE",
    },
    {
        "ambulance_id": "amb-002",
        "location": {"lat": 17.4399, "lng": 78.4983},
        "type": "BLS",
        "status": "ACTIVE",
    },
    {
        "ambulance_id": "amb-003",
        "location": {"lat": 17.4523, "lng": 78.3552},
        "type": "ALS",
        "status": "BUSY",
    },
    {
        "ambulance_id": "amb-004",
        "location": {"lat": 17.4358, "lng": 78.4469},
        "type": "BLS",
        "status": "OFFLINE",
    },
]


async def main() -> None:
    await connect_to_mongo()
    db = get_db()
    try:
        await db["ambulances"].delete_many({})
        print(f"Cleared 'ambulances' collection in '{settings.DB_NAME}'")

        for entry in AMBULANCES:
            doc = AmbulanceCreate(**entry).model_dump()
            await db["ambulances"].insert_one(doc)

        print(f"Inserted {len(AMBULANCES)} ambulances\n")
        header = f"{'Ambulance ID':<12}{'Type':>5}{'Status':>9}{'Location':>28}"
        print(header)
        print("-" * len(header))
        for entry in AMBULANCES:
            loc = entry["location"]
            location = f"{loc['lat']:.4f}, {loc['lng']:.4f}"
            print(
                f"{entry['ambulance_id']:<12}"
                f"{entry['type']:>5}"
                f"{entry['status']:>9}"
                f"{location:>28}"
            )
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(main())
