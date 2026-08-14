import asyncio
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.core.database import close_mongo_connection, connect_to_mongo, get_db
from app.models.hospital import HospitalCreate
from app.models.hospital_status import HospitalStatusCreate

random.seed(42)


def caps(
    emergency=False,
    trauma=False,
    icu=False,
    cardiology=False,
    neurology=False,
    ct=False,
    cath_lab=False,
    blood_bank=False,
    surgery=False,
    pediatrics=False,
    obstetrics=False,
):
    return {
        "emergency": emergency,
        "trauma": trauma,
        "icu": icu,
        "cardiology": cardiology,
        "neurology": neurology,
        "ct": ct,
        "cath_lab": cath_lab,
        "blood_bank": blood_bank,
        "surgery": surgery,
        "pediatrics": pediatrics,
        "obstetrics": obstetrics,
    }


HOSPITALS = [
    {
        "name": "Apollo Hospitals, Jubilee Hills",
        "location": {"lat": 17.4332, "lng": 78.4202},
        "capabilities": caps(
            emergency=True, trauma=True, icu=True, cardiology=True, neurology=True,
            ct=True, cath_lab=True, blood_bank=True, surgery=True,
            pediatrics=True, obstetrics=True,
        ),
    },
    {
        "name": "CARE Hospitals, Banjara Hills",
        "location": {"lat": 17.4163, "lng": 78.4490},
        "capabilities": caps(
            emergency=True, trauma=True, icu=True, cardiology=True, neurology=True,
            ct=True, cath_lab=True, blood_bank=True, surgery=True,
        ),
    },
    {
        "name": "Yashoda Hospitals, Secunderabad",
        "location": {"lat": 17.4399, "lng": 78.4983},
        "capabilities": caps(
            emergency=True, trauma=True, icu=True, cardiology=True, neurology=True,
            ct=True, cath_lab=True, blood_bank=True, surgery=True,
            pediatrics=True, obstetrics=True,
        ),
    },
    {
        "name": "KIMS Hospitals, Kondapur",
        "location": {"lat": 17.4523, "lng": 78.3552},
        "capabilities": caps(
            emergency=True, trauma=True, icu=True, cardiology=True,
            ct=True, cath_lab=True, blood_bank=True, surgery=True,
        ),
    },
    {
        "name": "Nizam's Institute of Medical Sciences (NIMS)",
        "location": {"lat": 17.4222, "lng": 78.4547},
        "capabilities": caps(
            emergency=True, trauma=True, icu=True, cardiology=True, neurology=True,
            ct=True, cath_lab=True, blood_bank=True, surgery=True,
            pediatrics=True, obstetrics=True,
        ),
    },
    {
        "name": "Gleneagles Global Hospitals, Lakdi Ka Pul",
        "location": {"lat": 17.3970, "lng": 78.4550},
        "capabilities": caps(
            emergency=True, trauma=True, icu=True, cardiology=True, neurology=True,
            ct=True, cath_lab=True, blood_bank=True, surgery=True,
        ),
    },
    {
        "name": "Gandhi Hospital, Secunderabad",
        "location": {"lat": 17.4435, "lng": 78.4892},
        "capabilities": caps(
            emergency=True, trauma=True, icu=True, ct=True, blood_bank=True,
            surgery=True, pediatrics=True, obstetrics=True,
        ),
    },
    {
        "name": "Sunshine Hospitals, Gachibowli",
        "location": {"lat": 17.4375, "lng": 78.3482},
        "capabilities": caps(
            emergency=True, trauma=True, icu=True, ct=True, blood_bank=True, surgery=True,
        ),
    },
    {
        "name": "Rainbow Children's Hospital, Banjara Hills",
        "location": {"lat": 17.4093, "lng": 78.4385},
        "capabilities": caps(
            emergency=True, icu=True, surgery=True, pediatrics=True, obstetrics=True,
        ),
    },
    {
        "name": "Fernandez Hospital, Bogulkunta",
        "location": {"lat": 17.3928, "lng": 78.4776},
        "capabilities": caps(emergency=True, pediatrics=True, obstetrics=True),
    },
    {
        "name": "City Clinic, Mehdipatnam",
        "location": {"lat": 17.4016, "lng": 78.4373},
        "capabilities": caps(emergency=True),
    },
    {
        "name": "Prime Clinic, Kukatpally",
        "location": {"lat": 17.4849, "lng": 78.4063},
        "capabilities": caps(emergency=True),
    },
    {
        "name": "Care General Clinic, Uppal",
        "location": {"lat": 17.4076, "lng": 78.5602},
        "capabilities": caps(emergency=True),
    },
    {
        "name": "Sai Neurology & Stroke Center, Ameerpet",
        "location": {"lat": 17.4358, "lng": 78.4469},
        "capabilities": caps(emergency=True, icu=True, neurology=True, ct=True),
    },
    {
        "name": "HeartCare Cardiac Institute, Ameerpet",
        "location": {"lat": 17.4300, "lng": 78.4500},
        "capabilities": caps(emergency=True, icu=True, cardiology=True, cath_lab=True),
    },
]


def make_status_doc(hospital_id: str, capabilities: dict, updated_at: datetime) -> dict:
    def dept_status(capable: bool) -> str:
        if not capable:
            return "UNAVAILABLE"
        return "AVAILABLE" if random.random() < 0.75 else "UNAVAILABLE"

    icu_total = random.randint(8, 40) if capabilities["icu"] else 0
    emergency_beds_total = random.randint(5, 30)
    return {
        "hospital_id": hospital_id,
        "icu_available": random.randint(0, icu_total) if icu_total else 0,
        "icu_total": icu_total,
        "emergency_beds_available": random.randint(0, emergency_beds_total),
        "emergency_beds_total": emergency_beds_total,
        "trauma_status": dept_status(capabilities["trauma"]),
        "cardiology_status": dept_status(capabilities["cardiology"]),
        "neurology_status": dept_status(capabilities["neurology"]),
        "ct_status": dept_status(capabilities["ct"]),
        "cath_lab_status": dept_status(capabilities["cath_lab"]),
        "accepting_patients": random.random() < 0.8,
        "updated_at": updated_at,
    }


def print_table(rows) -> None:
    header = f"{'Hospital':<44}{'Trauma':>7}{'ICU':>5}{'Stroke':>7}{'Cardiac':>8}{'Accepting':>10}"
    print(header)
    print("-" * len(header))
    for entry, status in rows:
        capabilities = entry["capabilities"]
        stroke = "YES" if capabilities["neurology"] and capabilities["ct"] else "no"
        cardiac = "YES" if capabilities["cardiology"] and capabilities["cath_lab"] else "no"
        print(
            f"{entry['name']:<44}"
            f"{'YES' if capabilities['trauma'] else 'no':>7}"
            f"{'YES' if capabilities['icu'] else 'no':>5}"
            f"{stroke:>7}"
            f"{cardiac:>8}"
            f"{'YES' if status['accepting_patients'] else 'no':>10}"
        )


def print_constraint_summary(rows) -> None:
    all_caps = [entry["capabilities"] for entry, _ in rows]
    full = sum(1 for c in all_caps if c["trauma"] and c["icu"] and c["blood_bank"])
    small = sum(1 for c in all_caps if not c["trauma"] and not c["icu"])
    stroke = sum(1 for c in all_caps if c["neurology"] and c["ct"])
    cardiac = sum(1 for c in all_caps if c["cardiology"] and c["cath_lab"])
    peds_obs = sum(1 for c in all_caps if c["pediatrics"] and c["obstetrics"] and not c["trauma"])
    print(f"\nFull trauma+ICU+blood_bank hospitals: {full}")
    print(f"Small clinics (no trauma/ICU): {small}")
    print(f"Stroke-capable (neurology+CT): {stroke}")
    print(f"Cardiac-capable (cardiology+cath_lab): {cardiac}")
    print(f"Pediatric/obstetric-focused: {peds_obs}")


async def main() -> None:
    await connect_to_mongo()
    db = get_db()
    try:
        await db["hospitals"].delete_many({})
        await db["hospital_status"].delete_many({})
        print(f"Cleared 'hospitals' and 'hospital_status' collections in '{settings.DB_NAME}'")

        now = datetime.now(timezone.utc)
        rows = []
        for entry in HOSPITALS:
            hospital_doc = HospitalCreate(**entry).model_dump()
            hospital_doc["created_at"] = now
            result = await db["hospitals"].insert_one(hospital_doc)
            hospital_id = str(result.inserted_id)

            status_data = make_status_doc(hospital_id, entry["capabilities"], now)
            status_doc = HospitalStatusCreate(**status_data).model_dump()
            status_doc["updated_at"] = now
            await db["hospital_status"].insert_one(status_doc)
            rows.append((entry, status_doc))

        print(f"Inserted {len(rows)} hospitals with matching hospital_status documents\n")
        print_table(rows)
        print_constraint_summary(rows)
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(main())
