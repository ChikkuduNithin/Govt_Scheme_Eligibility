import asyncio

import pytest

from app.core.config import settings
from app.services.decision_engine import (
    estimate_wait_time,
    recommend_hospital,
    treatment_readiness_minutes,
)

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

AMBULANCE = {"lat": 17.4000, "lng": 78.4500}

TRAUMA_CASE = {"case_id": "case-001", "emergency_type": "TRAUMA", "severity": "HIGH"}


def hospital(hid, location, capabilities=None):
    return {
        "_id": hid,
        "name": f"Hospital {hid}",
        "location": location,
        "capabilities": capabilities if capabilities is not None else dict(FULL_CAPS),
    }


def status(
    hid,
    accepting=True,
    icu=10,
    beds_available=5,
    beds_total=10,
    trauma="AVAILABLE",
    cardiology="AVAILABLE",
    neurology="AVAILABLE",
    ct="AVAILABLE",
    cath_lab="AVAILABLE",
):
    return {
        "hospital_id": hid,
        "accepting_patients": accepting,
        "icu_available": icu,
        "icu_total": 20,
        "emergency_beds_available": beds_available,
        "emergency_beds_total": beds_total,
        "trauma_status": trauma,
        "cardiology_status": cardiology,
        "neurology_status": neurology,
        "ct_status": ct,
        "cath_lab_status": cath_lab,
    }


def statuses(*docs):
    return {s["hospital_id"]: s for s in docs}


def run(case, hospitals, hospital_statuses, ambulance=AMBULANCE):
    return asyncio.run(recommend_hospital(case, hospitals, hospital_statuses, ambulance))


def test_design_doc_scenario_b_wins(monkeypatch):
    monkeypatch.setattr(settings, "AVG_URBAN_SPEED_KMH", 30.0)
    hospitals = [
        hospital("A", {"lat": 17.4200, "lng": 78.4600}),
        hospital("B", {"lat": 17.4010, "lng": 78.4505}),
        hospital(
            "C",
            {"lat": 17.4100, "lng": 78.4700},
            capabilities={**FULL_CAPS, "trauma": False},
        ),
        hospital("D", {"lat": 17.4300, "lng": 78.4800}),
    ]
    hospital_statuses = statuses(
        status("A", icu=0),
        status("B"),
        status("C"),
        status("D"),
    )

    result = run(TRAUMA_CASE, hospitals, hospital_statuses)

    assert result["case_id"] == "case-001"
    assert result["recommended_hospital_id"] == "B"
    assert result["eta_minutes"] > 0
    assert result["total_care_delay_minutes"] == pytest.approx(result["eta_minutes"] + 9.0, abs=0.2)
    assert "Required Trauma capability" in result["reasons"]
    assert "ICU available" in result["reasons"]
    assert any(reason.startswith("ETA:") for reason in result["reasons"])

    assert [a["hospital_id"] for a in result["alternatives"]] == ["D", "A", "C"]
    by_id = {a["hospital_id"]: a for a in result["alternatives"]}
    assert by_id["A"]["eliminated_reason"] == "No ICU beds available"
    assert by_id["C"]["eliminated_reason"] == "Trauma capability unavailable"
    assert by_id["D"]["eliminated_reason"] is None
    assert by_id["D"]["total_care_delay_minutes"] is not None
    assert by_id["D"]["total_care_delay_minutes"] > result["total_care_delay_minutes"]


def test_zero_eligible_returns_no_eligible_hospital():
    hospitals = [
        hospital("A", {"lat": 17.4200, "lng": 78.4600}),
        hospital("B", {"lat": 17.4010, "lng": 78.4505}),
    ]
    hospital_statuses = statuses(
        status("A", accepting=False),
        status("B", accepting=False),
    )

    result = run(TRAUMA_CASE, hospitals, hospital_statuses)

    assert result["no_eligible_hospital"] is True
    assert result["recommended_hospital_id"] is None
    assert result["eta_minutes"] is None
    assert result["total_care_delay_minutes"] is None
    assert result["reasons"] == []
    reasons = {a["hospital_id"]: a["eliminated_reason"] for a in result["alternatives"]}
    assert reasons == {
        "A": "Hospital not accepting patients",
        "B": "Hospital not accepting patients",
    }


def test_stroke_case_requires_ct(monkeypatch):
    monkeypatch.setattr(settings, "AVG_URBAN_SPEED_KMH", 30.0)
    case = {"case_id": "case-002", "emergency_type": "STROKE", "severity": "HIGH"}
    hospitals = [hospital("B", {"lat": 17.4010, "lng": 78.4505})]
    hospital_statuses = statuses(status("B"))

    result = run(case, hospitals, hospital_statuses)

    assert result["recommended_hospital_id"] == "B"
    assert "Required CT capability" in result["reasons"]
    assert result["total_care_delay_minutes"] == pytest.approx(result["eta_minutes"] + 10.0, abs=0.2)


def test_no_eligible_alternatives_carry_reasons_from_mixed_failures():
    hospitals = [
        hospital("NO_STATUS", {"lat": 17.4200, "lng": 78.4600}),
        hospital("NO_TRAUMA", {"lat": 17.4100, "lng": 78.4700}, capabilities={**FULL_CAPS, "trauma": False}),
    ]
    hospital_statuses = statuses(status("NO_TRAUMA"))

    result = run(TRAUMA_CASE, hospitals, hospital_statuses)

    assert result["no_eligible_hospital"] is True
    reasons = {a["hospital_id"]: a["eliminated_reason"] for a in result["alternatives"]}
    assert reasons == {
        "NO_STATUS": "No hospital status available",
        "NO_TRAUMA": "Trauma capability unavailable",
    }


def test_estimate_wait_time_bed_occupancy():
    base = {"icu_available": 5, "emergency_beds_available": 10, "emergency_beds_total": 10}
    assert estimate_wait_time(base) == 5.0
    half = {**base, "emergency_beds_available": 5}
    assert estimate_wait_time(half) == 6.0
    empty = {**base, "emergency_beds_available": 0}
    assert estimate_wait_time(empty) == 7.0


def test_estimate_wait_time_icu_penalty():
    no_icu = {"icu_available": 0, "emergency_beds_available": 10, "emergency_beds_total": 10}
    assert estimate_wait_time(no_icu, {"icu": True}) == 10.0
    assert estimate_wait_time(no_icu, {"icu": False}) == 5.0
    assert estimate_wait_time(no_icu, {}) == 5.0


def test_treatment_readiness_lookup():
    assert treatment_readiness_minutes("TRAUMA") == 3.0
    assert treatment_readiness_minutes("STROKE") == 4.0
    assert treatment_readiness_minutes("CARDIAC") == 3.0
    assert treatment_readiness_minutes("RESPIRATORY") == 5.0
