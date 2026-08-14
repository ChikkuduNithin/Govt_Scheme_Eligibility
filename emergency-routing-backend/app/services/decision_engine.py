from app.services.clinical_requirements import get_required_capabilities
from app.services.eligibility_filter import CAPABILITY_LABELS, filter_eligible_hospitals
from app.services.eta_service import get_eta

TREATMENT_READINESS_MINUTES = {
    "TRAUMA": 3,
    "STROKE": 4,
    "CARDIAC": 3,
}


def estimate_wait_time(status: dict, required_capabilities: dict | None = None) -> float:
    required_capabilities = required_capabilities or {}
    base_wait = 5.0
    beds_total = status.get("emergency_beds_total") or 1
    beds_available = max(status.get("emergency_beds_available") or 0, 0)
    occupied_fraction = 1.0 - min(1.0, beds_available / beds_total)
    wait = base_wait + 2.0 * occupied_fraction
    if required_capabilities.get("icu") is True and (status.get("icu_available") or 0) == 0:
        wait += 5.0
    return round(wait, 1)


def treatment_readiness_minutes(emergency_type: str) -> float:
    return float(TREATMENT_READINESS_MINUTES.get(emergency_type, 5))


async def recommend_hospital(
    case: dict,
    hospitals: list[dict],
    hospital_statuses: dict,
    ambulance_location: dict,
) -> dict:
    required_capabilities = get_required_capabilities(
        case["emergency_type"], case["severity"]
    )
    eligible, eliminated = filter_eligible_hospitals(
        hospitals, hospital_statuses, required_capabilities
    )
    case_id = case.get("case_id", "")

    scored = []
    for hospital in eligible:
        hospital_id = str(hospital["_id"])
        status = hospital_statuses[hospital_id]
        eta = await get_eta(ambulance_location, hospital["location"])
        eta_minutes = eta["eta_minutes"]
        wait = estimate_wait_time(status, required_capabilities)
        readiness = treatment_readiness_minutes(case["emergency_type"])
        scored.append(
            {
                "hospital": hospital,
                "hospital_id": hospital_id,
                "status": status,
                "eta_minutes": eta_minutes,
                "expected_wait_minutes": wait,
                "treatment_readiness_minutes": readiness,
                "total_care_delay_minutes": round(eta_minutes + wait + readiness, 1),
            }
        )

    if not scored:
        return _build_no_eligible_result(case_id, eliminated)

    scored.sort(key=lambda entry: entry["total_care_delay_minutes"])
    top = scored[0]

    alternatives = []
    for entry in scored[1:]:
        alternatives.append(
            {
                "hospital_id": entry["hospital_id"],
                "eliminated_reason": None,
                "total_care_delay_minutes": entry["total_care_delay_minutes"],
            }
        )
    for hospital in eliminated:
        alternatives.append(
            {
                "hospital_id": str(hospital["_id"]),
                "eliminated_reason": hospital["eliminated_reason"],
                "total_care_delay_minutes": None,
            }
        )

    return {
        "case_id": case_id,
        "recommended_hospital_id": top["hospital_id"],
        "eta_minutes": top["eta_minutes"],
        "total_care_delay_minutes": top["total_care_delay_minutes"],
        "reasons": _build_reasons(top, required_capabilities),
        "alternatives": alternatives,
    }


def _build_reasons(scored: dict, required_capabilities: dict) -> list[str]:
    status = scored["status"]
    reasons = []
    for cap, required in required_capabilities.items():
        if required is not True:
            continue
        if cap == "icu":
            if (status.get("icu_available") or 0) > 0:
                reasons.append("ICU available")
            else:
                reasons.append("ICU required but unavailable")
        else:
            reasons.append(f"Required {CAPABILITY_LABELS.get(cap, cap)} capability")
    reasons.append(f"ETA: {scored['eta_minutes']:.0f} min")
    reasons.append(f"Expected wait: {scored['expected_wait_minutes']:.0f} min")
    reasons.append(f"Total care delay: {scored['total_care_delay_minutes']:.0f} min")
    return reasons


def _build_no_eligible_result(case_id: str, eliminated: list[dict]) -> dict:
    return {
        "case_id": case_id,
        "recommended_hospital_id": None,
        "eta_minutes": None,
        "total_care_delay_minutes": None,
        "reasons": [],
        "no_eligible_hospital": True,
        "alternatives": [
            {
                "hospital_id": str(hospital["_id"]),
                "eliminated_reason": hospital["eliminated_reason"],
                "total_care_delay_minutes": None,
            }
            for hospital in eliminated
        ],
    }
