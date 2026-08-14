import pytest
from datetime import datetime, timedelta, timezone

from app.services.eligibility_filter import filter_eligible_hospitals
from app.core.config import settings

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

TRAUMA_HIGH_REQ = {"emergency": True, "trauma": True, "surgery": True, "blood_bank": True, "icu": True}


def hospital(hid, capabilities=None):
    return {
        "_id": hid,
        "name": f"Hospital {hid}",
        "capabilities": capabilities if capabilities is not None else dict(FULL_CAPS),
    }


def status(
    hid,
    accepting=True,
    icu=10,
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
        "emergency_beds_available": 5,
        "emergency_beds_total": 10,
        "trauma_status": trauma,
        "cardiology_status": cardiology,
        "neurology_status": neurology,
        "ct_status": ct,
        "cath_lab_status": cath_lab,
    }


def statuses(*docs):
    return {s["hospital_id"]: s for s in docs}


def test_design_doc_scenario():
    hospitals = [
        hospital("A"),
        hospital("B"),
        hospital("C", capabilities={**FULL_CAPS, "trauma": False}),
        hospital("D"),
    ]
    hospital_statuses = statuses(
        status("A", icu=0),
        status("B"),
        status("C"),
        status("D"),
    )

    eligible, eliminated = filter_eligible_hospitals(hospitals, hospital_statuses, TRAUMA_HIGH_REQ)

    assert [h["_id"] for h in eligible] == ["B", "D"]
    assert {h["_id"]: h["eliminated_reason"] for h in eliminated} == {
        "A": "No ICU beds available",
        "C": "Trauma capability unavailable",
    }


def test_stroke_ct_unavailable_eliminates():
    hospitals = [
        hospital("CT_STATUS_DOWN", capabilities={**FULL_CAPS, "icu": False}),
        hospital("NO_CT_CAP", capabilities={**FULL_CAPS, "ct": False, "icu": False}),
        hospital("OK", capabilities={**FULL_CAPS, "icu": False}),
    ]
    hospital_statuses = statuses(
        status("CT_STATUS_DOWN", ct="UNAVAILABLE"),
        status("NO_CT_CAP"),
        status("OK"),
    )
    req = {"emergency": True, "ct": True, "neurology": "preferred", "icu": False}

    eligible, eliminated = filter_eligible_hospitals(hospitals, hospital_statuses, req)

    assert [h["_id"] for h in eligible] == ["OK"]
    assert {h["_id"]: h["eliminated_reason"] for h in eliminated} == {
        "CT_STATUS_DOWN": "CT capability unavailable",
        "NO_CT_CAP": "CT capability unavailable",
    }


def test_stroke_preferred_neurology_does_not_eliminate():
    hospitals = [hospital("NO_NEURO", capabilities={**FULL_CAPS, "neurology": False, "icu": False})]
    hospital_statuses = statuses(status("NO_NEURO"))
    req = {"emergency": True, "ct": True, "neurology": "preferred", "icu": False}

    eligible, eliminated = filter_eligible_hospitals(hospitals, hospital_statuses, req)

    assert [h["_id"] for h in eligible] == ["NO_NEURO"]
    assert eliminated == []


def test_cardiac_department_statuses_eliminate():
    hospitals = [
        hospital("CARDIO_DOWN"),
        hospital("CATH_DOWN"),
        hospital("NO_ICU", capabilities={**FULL_CAPS}),
        hospital("OK"),
    ]
    hospital_statuses = statuses(
        status("CARDIO_DOWN", cardiology="UNAVAILABLE"),
        status("CATH_DOWN", cath_lab="UNAVAILABLE"),
        status("NO_ICU", icu=0),
        status("OK"),
    )
    req = {"emergency": True, "cardiology": True, "cath_lab": True, "icu": True}

    eligible, eliminated = filter_eligible_hospitals(hospitals, hospital_statuses, req)

    assert [h["_id"] for h in eligible] == ["OK"]
    assert {h["_id"]: h["eliminated_reason"] for h in eliminated} == {
        "CARDIO_DOWN": "Cardiology capability unavailable",
        "CATH_DOWN": "Cath lab capability unavailable",
        "NO_ICU": "No ICU beds available",
    }


def test_not_accepting_patients_eliminated():
    hospitals = [hospital("FULL")]
    hospital_statuses = statuses(status("FULL", accepting=False))

    eligible, eliminated = filter_eligible_hospitals(hospitals, hospital_statuses, TRAUMA_HIGH_REQ)

    assert eligible == []
    assert eliminated[0]["_id"] == "FULL"
    assert eliminated[0]["eliminated_reason"] == "Hospital not accepting patients"


def test_missing_status_eliminated():
    hospitals = [hospital("NO_STATUS")]

    eligible, eliminated = filter_eligible_hospitals(hospitals, {}, TRAUMA_HIGH_REQ)

    assert eligible == []
    assert eliminated[0]["_id"] == "NO_STATUS"
    assert eliminated[0]["eliminated_reason"] == "No hospital status available"


def test_obstetric_preferred_surgery_does_not_eliminate():
    hospitals = [
        hospital("OK", capabilities={**FULL_CAPS, "surgery": False, "icu": False}),
    ]
    hospital_statuses = statuses(status("OK"))
    req = {"emergency": True, "obstetrics": True, "surgery": "preferred"}

    eligible, eliminated = filter_eligible_hospitals(hospitals, hospital_statuses, req)

    assert [h["_id"] for h in eligible] == ["OK"]
    assert eliminated == []


def test_low_severity_icu_not_required():
    hospitals = [hospital("NO_ICU_BEDS")]
    hospital_statuses = statuses(status("NO_ICU_BEDS", icu=0))
    req = {"emergency": True, "trauma": True, "surgery": True, "blood_bank": True, "icu": False}

    eligible, eliminated = filter_eligible_hospitals(hospitals, hospital_statuses, req)

    assert [h["_id"] for h in eligible] == ["NO_ICU_BEDS"]
    assert eliminated == []


def test_input_hospitals_not_mutated():
    original = hospital("A")
    hospital_statuses = statuses(status("A"))
    hospitals = [original]

    filter_eligible_hospitals(hospitals, hospital_statuses, TRAUMA_HIGH_REQ)

    assert "eliminated_reason" not in original


def test_eliminated_entries_are_copies():
    original = hospital("A")
    hospital_statuses = statuses(status("A", icu=0))

    _, eliminated = filter_eligible_hospitals([original], hospital_statuses, TRAUMA_HIGH_REQ)

    assert eliminated[0] is not original
    assert "eliminated_reason" not in original
    expected = {**original, "eliminated_reason": "No ICU beds available"}
    assert eliminated[0] == expected


def test_fresh_status_eligible():
    hospitals = [hospital("A")]
    hospital_statuses = statuses(status("A"))

    eligible, eliminated = filter_eligible_hospitals(
        hospitals, hospital_statuses, TRAUMA_HIGH_REQ
    )

    assert [h["_id"] for h in eligible] == ["A"]
    assert eliminated == []


def test_stale_status_eliminated(monkeypatch):
    monkeypatch.setattr(settings, "MAX_STATUS_AGE_SECONDS", 60)
    hospitals = [hospital("A")]
    stale = status("A")
    stale["updated_at"] = datetime.now(timezone.utc) - timedelta(minutes=10)
    hospital_statuses = statuses(stale)

    eligible, eliminated = filter_eligible_hospitals(
        hospitals, hospital_statuses, TRAUMA_HIGH_REQ
    )

    assert eligible == []
    assert eliminated[0]["_id"] == "A"
    assert eliminated[0]["eliminated_reason"] == "Hospital status is stale"


def test_missing_updated_at_treated_as_fresh():
    hospitals = [hospital("A")]
    hospital_statuses = statuses(status("A"))

    eligible, _ = filter_eligible_hospitals(
        hospitals, hospital_statuses, TRAUMA_HIGH_REQ,
        now=datetime.now(timezone.utc) + timedelta(hours=2),
    )

    assert [h["_id"] for h in eligible] == ["A"]
