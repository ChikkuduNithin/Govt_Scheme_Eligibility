from datetime import datetime, timezone

from app.core.config import settings

CAPABILITY_LABELS = {
    "emergency": "Emergency",
    "trauma": "Trauma",
    "icu": "ICU",
    "cardiology": "Cardiology",
    "neurology": "Neurology",
    "ct": "CT",
    "cath_lab": "Cath lab",
    "blood_bank": "Blood bank",
    "surgery": "Surgery",
    "pediatrics": "Pediatrics",
    "obstetrics": "Obstetrics",
}


def filter_eligible_hospitals(
    hospitals: list[dict],
    hospital_statuses: dict[str, dict],
    required_capabilities: dict,
    now: datetime | None = None,
) -> tuple[list[dict], list[dict]]:
    hard_required = [cap for cap, value in required_capabilities.items() if value is True]
    now = now or datetime.now(timezone.utc)

    eligible = []
    eliminated = []

    for hospital in hospitals:
        reason = _elimination_reason(hospital, hospital_statuses, hard_required, now)
        if reason is None:
            eligible.append(hospital)
        else:
            eliminated_hospital = dict(hospital)
            eliminated_hospital["eliminated_reason"] = reason
            eliminated.append(eliminated_hospital)

    return eligible, eliminated


def _elimination_reason(
    hospital: dict,
    hospital_statuses: dict[str, dict],
    hard_required: list[str],
    now: datetime,
) -> str | None:
    hospital_id = str(hospital.get("_id", ""))
    status = hospital_statuses.get(hospital_id)
    if status is None:
        return "No hospital status available"
    if not status.get("accepting_patients", False):
        return "Hospital not accepting patients"
    if _is_stale(status, now):
        return "Hospital status is stale"

    capabilities = hospital.get("capabilities") or {}
    for cap in hard_required:
        if not capabilities.get(cap, False):
            return f"{CAPABILITY_LABELS.get(cap, cap)} capability unavailable"

    if "icu" in hard_required and (status.get("icu_available") or 0) <= 0:
        return "No ICU beds available"
    if "trauma" in hard_required and status.get("trauma_status") != "AVAILABLE":
        return "Trauma capability unavailable"
    if "cardiology" in hard_required and status.get("cardiology_status") != "AVAILABLE":
        return "Cardiology capability unavailable"
    if "cath_lab" in hard_required and status.get("cath_lab_status") != "AVAILABLE":
        return "Cath lab capability unavailable"
    if "neurology" in hard_required and status.get("neurology_status") != "AVAILABLE":
        return "Neurology capability unavailable"
    if "ct" in hard_required and status.get("ct_status") != "AVAILABLE":
        return "CT capability unavailable"

    return None


def _is_stale(status: dict, now: datetime) -> bool:
    updated_at = status.get("updated_at")
    if not isinstance(updated_at, datetime):
        return False
    try:
        age_seconds = (now - updated_at).total_seconds()
    except TypeError:
        return False
    return age_seconds > settings.MAX_STATUS_AGE_SECONDS
