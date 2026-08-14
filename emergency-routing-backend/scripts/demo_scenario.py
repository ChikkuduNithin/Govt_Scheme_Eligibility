"""Rehearse the design doc's Hospital A/B/C demo scenario against a running server.

Run the backend first, then:

    python scripts/demo_scenario.py [--base-url http://localhost:8000] [--skip-seed]

The scenario:
  Hospital A  City Clinic, Mehdipatnam   closest to the ambulance, but an
                                         emergency-only clinic -> eliminated
  Hospital B  Gleneagles Global Hospital best full trauma center -> recommended
  Hospital C  CARE Hospitals, Banjara     second-best trauma center -> the
              Hills                       re-route target when B fills up
"""

import argparse
import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import seed_hospitals
from app.services.eta_service import _haversine_km

AMBULANCE_ID = "amb-demo-001"
AMBULANCE_LOCATION = {"lat": 17.3990, "lng": 78.4440}

HOSPITAL_NAMES = {
    "A": "City Clinic, Mehdipatnam",
    "B": "Gleneagles Global Hospitals, Lakdi Ka Pul",
    "C": "CARE Hospitals, Banjara Hills",
}

STATUS_B = {
    "icu_available": 6,
    "icu_total": 10,
    "emergency_beds_available": 8,
    "emergency_beds_total": 8,
    "trauma_status": "AVAILABLE",
    "cardiology_status": "AVAILABLE",
    "neurology_status": "AVAILABLE",
    "ct_status": "AVAILABLE",
    "cath_lab_status": "AVAILABLE",
    "accepting_patients": True,
}

STATUS_C = {
    "icu_available": 4,
    "icu_total": 12,
    "emergency_beds_available": 10,
    "emergency_beds_total": 10,
    "trauma_status": "AVAILABLE",
    "cardiology_status": "AVAILABLE",
    "neurology_status": "AVAILABLE",
    "ct_status": "AVAILABLE",
    "cath_lab_status": "AVAILABLE",
    "accepting_patients": True,
}

STATUS_A = {
    "icu_available": 0,
    "icu_total": 0,
    "emergency_beds_available": 2,
    "emergency_beds_total": 6,
    "trauma_status": "UNAVAILABLE",
    "cardiology_status": "UNAVAILABLE",
    "neurology_status": "UNAVAILABLE",
    "ct_status": "UNAVAILABLE",
    "cath_lab_status": "UNAVAILABLE",
    "accepting_patients": True,
}


def banner(title: str) -> None:
    print(f"\n{'=' * 62}")
    print(f"  {title}")
    print(f"{'=' * 62}")


def section(number: int, title: str) -> None:
    print(f"\n[{number}] {title}")


def bullet(text: str) -> None:
    print(f"  - {text}")


def label(key: str, value) -> None:
    print(f"  {key:<28} {value}")


class DemoError(RuntimeError):
    pass


def api_error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    detail = data.get("detail", f"HTTP {response.status_code}")
    if isinstance(detail, list):
        return "; ".join(
            f"{item.get('loc', '')}: {item.get('msg', '')}" for item in detail
        )
    return str(detail)


async def api(client: httpx.AsyncClient, method: str, path: str, body=None) -> dict:
    response = await client.request(method, path, json=body)
    if response.status_code >= 400:
        raise DemoError(f"{method} {path} failed ({api_error_message(response)})")
    return response.json()


async def ensure_seeded() -> None:
    section(1, "Ensuring hospitals are seeded")
    print("  Running scripts/seed_hospitals.py ...")
    await seed_hospitals.main()
    print("  Hospitals and fresh statuses are ready.")


async def resolve_hospitals(client: httpx.AsyncClient) -> dict:
    section(2, "Resolving scenario hospitals (by name)")
    hospitals = await api(client, "GET", "/api/v1/hospitals")
    by_name = {hospital["name"]: hospital for hospital in hospitals}
    resolved = {}
    for key, name in HOSPITAL_NAMES.items():
        hospital = by_name.get(name)
        if hospital is None:
            raise DemoError(f"Seeded hospital not found: {name}")
        resolved[key] = hospital
        eta = _haversine_km(
            AMBULANCE_LOCATION["lat"],
            AMBULANCE_LOCATION["lng"],
            hospital["location"]["lat"],
            hospital["location"]["lng"],
        )
        print(
            f"  {key}  {name:<42} "
            f"({eta / 30.0 * 60.0:.1f} min from ambulance)"
        )
    return resolved


async def ensure_ambulance(client: httpx.AsyncClient) -> None:
    section(3, f"Registering ambulance {AMBULANCE_ID}")
    body = {
        "ambulance_id": AMBULANCE_ID,
        "location": AMBULANCE_LOCATION,
        "type": "ALS",
        "status": "ACTIVE",
    }
    try:
        await api(client, "POST", "/api/v1/ambulances", body)
        print("  Ambulance registered.")
    except DemoError as error:
        if "already registered" in str(error):
            await api(
                client,
                "PATCH",
                f"/api/v1/ambulances/{AMBULANCE_ID}",
                {"location": AMBULANCE_LOCATION, "status": "ACTIVE"},
            )
            print("  Ambulance already existed - reset location/status.")
        else:
            raise
    location = AMBULANCE_LOCATION
    print(f"  Position: {location['lat']}, {location['lng']} (near Lakdi Ka Pul)")


async def create_emergency(client: httpx.AsyncClient) -> str:
    section(4, "Creating a severe trauma case")
    body = {
        "emergency_type": "TRAUMA",
        "severity": "HIGH",
        "patient": {
            "age": 34,
            "conscious": False,
            "spo2": 91,
            "heart_rate": 118,
            "bp": "90/60",
        },
        "ambulance_id": AMBULANCE_ID,
    }
    created = await api(client, "POST", "/api/v1/emergencies", body)
    case_id = created["case_id"]
    print("  Trauma / HIGH severity - unconscious, hypotensive")
    print("  Patient: age 34, SpO2 91, HR 118, BP 90/60")
    print(f"  Case ID: {case_id}")
    return case_id


async def push_status(client: httpx.AsyncClient, hospital: dict, fields: dict) -> dict:
    body = {"hospital_id": hospital["_id"], **fields}
    return await api(
        client, "POST", f"/api/v1/hospitals/{hospital['_id']}/status", body
    )


async def set_deterministic_statuses(client: httpx.AsyncClient, hospitals: dict) -> None:
    section(5, "Pinning statuses so the demo outcome is deterministic")
    await push_status(client, hospitals["A"], STATUS_A)
    print("  A  City Clinic: emergency-only, no trauma/ICU beds")
    await push_status(client, hospitals["B"], STATUS_B)
    print("  B  Gleneagles: ICU 6/10, emergency 8/8, all units AVAILABLE")
    await push_status(client, hospitals["C"], STATUS_C)
    print("  C  CARE: ICU 4/12, emergency 10/10, all units AVAILABLE")


async def recommend(client: httpx.AsyncClient, case_id: str) -> dict:
    return await api(client, "POST", f"/api/v1/emergencies/{case_id}/recommend")


def hospital_name(hospitals: dict, hospital_id: str) -> str:
    for hospital in hospitals.values():
        if hospital["_id"] == hospital_id:
            return hospital["name"]
    return hospital_id


def print_recommendation(hospitals: dict, recommendation: dict) -> None:
    top_id = recommendation["recommended_hospital_id"]
    if top_id is None:
        print("  RECOMMENDED: no eligible hospital")
        return
    print(
        f"  RECOMMENDED: {hospital_name(hospitals, top_id)}"
    )
    label("ETA", f'{recommendation["eta_minutes"]} min')
    label("Total care delay", f'{recommendation["total_care_delay_minutes"]} min')
    print("  Reasons:")
    for reason in recommendation["reasons"]:
        bullet(reason)

    alternatives = recommendation["alternatives"]
    eligible = [alt for alt in alternatives if alt["eliminated_reason"] is None]
    eliminated = [alt for alt in alternatives if alt["eliminated_reason"] is not None]
    print(f"  Alternatives considered: {len(alternatives)} "
          f"({len(eligible)} eligible, {len(eliminated)} eliminated)")
    for key, hospital in hospitals.items():
        if hospital["_id"] == top_id:
            continue
        alt = next(
            (a for a in alternatives if a["hospital_id"] == hospital["_id"]), None
        )
        if alt is None:
            continue
        if alt["eliminated_reason"]:
            print(f"  {key} was eliminated: {alt['eliminated_reason']}")
        else:
            print(
                f"  {key} is the backup: "
                f'{alt["total_care_delay_minutes"]} min total delay'
            )


async def run(base_url: str, skip_seed: bool = False) -> None:
    banner(
        "EMERGENCY ROUTING - LIVE DEMO SCENARIO\n"
        "  A: close but unsuitable   B: best   C: suitable backup"
    )

    async with httpx.AsyncClient(base_url=base_url, timeout=15.0) as client:
        if skip_seed:
            section(1, "Skipping seed (--skip-seed)")
            print("  Assuming hospitals are already seeded.")
        else:
            await ensure_seeded()
        hospitals = await resolve_hospitals(client)
        await ensure_ambulance(client)
        case_id = await create_emergency(client)
        await set_deterministic_statuses(client, hospitals)

        section(6, "Decision engine (before) - Hospital B should win")
        before = await recommend(client, case_id)
        print_recommendation(hospitals, before)
        before_top = before["recommended_hospital_id"]
        before_top_name = hospital_name(hospitals, before_top)

        section(7, "Hospital B's ICU fills up (available beds 6 -> 0)")
        await push_status(
            client,
            hospitals["B"],
            {**STATUS_B, "icu_available": 0},
        )
        print(
            f"  POST /api/v1/hospitals/{hospitals['B']['_id']}/status "
            "with icu_available=0"
        )

        section(8, "Decision engine (after) - re-routes to Hospital C")
        after = await recommend(client, case_id)
        print_recommendation(hospitals, after)
        after_top = after["recommended_hospital_id"]
        after_top_name = hospital_name(hospitals, after_top)

        banner("BEFORE / AFTER SUMMARY")
        print(f"  BEFORE  Hospital B ({before_top_name}) is recommended")
        print(f"          ETA {before['eta_minutes']} min | "
              f"delay {before['total_care_delay_minutes']} min")
        print(f"          A eliminated: Trauma capability unavailable")
        print()
        print(f"  EVENT   Hospital B ICU drops to 0 available beds")
        print(f"          -> B becomes ineligible (No ICU beds available)")
        print()
        print(f"  AFTER   Hospital C ({after_top_name}) is recommended instead")
        print(f"          ETA {after['eta_minutes']} min | "
              f"delay {after['total_care_delay_minutes']} min")
        print()
        a_eta = _haversine_km(
            AMBULANCE_LOCATION["lat"],
            AMBULANCE_LOCATION["lng"],
            hospitals["A"]["location"]["lat"],
            hospitals["A"]["location"]["lng"],
        ) / 30.0 * 60.0
        print("  NARRATION")
        print(f"    A is closest to the ambulance ({a_eta:.1f} min) but has no trauma")
        print("    capacity, so the engine eliminates it immediately.")
        print(f"    B is the best full trauma center "
              f"(delay {before['total_care_delay_minutes']} min).")
        print("    When B's ICU fills up, the engine falls back to C "
              f"(delay {after['total_care_delay_minutes']} min).")
        print()
        print(f"  Case: {case_id}  Ambulance: {AMBULANCE_ID}")
        print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rehearse the Hospital A/B/C demo scenario."
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of the running FastAPI server (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--skip-seed",
        action="store_true",
        help="Do not re-run scripts/seed_hospitals.py first",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    try:
        await run(args.base_url, skip_seed=args.skip_seed)
    except httpx.ConnectError as error:
        print(f"\nERROR: cannot reach the server at {args.base_url}")
        print(f"  {error}")
        print("  Start it with: uvicorn app.main:app --reload")
        sys.exit(1)
    except DemoError as error:
        print(f"\nERROR: {error}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
