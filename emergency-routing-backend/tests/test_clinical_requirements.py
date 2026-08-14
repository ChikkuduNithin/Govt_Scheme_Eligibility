import pytest

from app.services.clinical_requirements import get_required_capabilities

EMERGENCY_TYPES = [
    "TRAUMA",
    "STROKE",
    "CARDIAC",
    "RESPIRATORY",
    "BURN",
    "PEDIATRIC",
    "OBSTETRIC",
    "GENERAL_CRITICAL",
]
SEVERITIES = ["LOW", "MEDIUM", "HIGH"]

EXPECTED = {
    ("TRAUMA", "LOW"): {
        "emergency": True,
        "trauma": True,
        "surgery": True,
        "blood_bank": True,
        "icu": False,
    },
    ("TRAUMA", "MEDIUM"): {
        "emergency": True,
        "trauma": True,
        "surgery": True,
        "blood_bank": True,
        "icu": False,
    },
    ("TRAUMA", "HIGH"): {
        "emergency": True,
        "trauma": True,
        "surgery": True,
        "blood_bank": True,
        "icu": True,
    },
    ("STROKE", "LOW"): {
        "emergency": True,
        "ct": True,
        "neurology": "preferred",
        "icu": False,
    },
    ("STROKE", "MEDIUM"): {
        "emergency": True,
        "ct": True,
        "neurology": "preferred",
        "icu": False,
    },
    ("STROKE", "HIGH"): {
        "emergency": True,
        "ct": True,
        "neurology": "preferred",
        "icu": True,
    },
    ("CARDIAC", "LOW"): {
        "emergency": True,
        "cardiology": True,
        "cath_lab": "preferred",
        "icu": False,
    },
    ("CARDIAC", "MEDIUM"): {
        "emergency": True,
        "cardiology": True,
        "cath_lab": True,
        "icu": False,
    },
    ("CARDIAC", "HIGH"): {
        "emergency": True,
        "cardiology": True,
        "cath_lab": True,
        "icu": True,
    },
    ("RESPIRATORY", "LOW"): {
        "emergency": True,
        "icu": False,
    },
    ("RESPIRATORY", "MEDIUM"): {
        "emergency": True,
        "icu": False,
    },
    ("RESPIRATORY", "HIGH"): {
        "emergency": True,
        "icu": True,
    },
    ("BURN", "LOW"): {
        "emergency": True,
        "surgery": True,
        "icu": False,
    },
    ("BURN", "MEDIUM"): {
        "emergency": True,
        "surgery": True,
        "icu": False,
    },
    ("BURN", "HIGH"): {
        "emergency": True,
        "surgery": True,
        "icu": True,
    },
    ("PEDIATRIC", "LOW"): {
        "emergency": True,
        "pediatrics": True,
        "icu": False,
    },
    ("PEDIATRIC", "MEDIUM"): {
        "emergency": True,
        "pediatrics": True,
        "icu": False,
    },
    ("PEDIATRIC", "HIGH"): {
        "emergency": True,
        "pediatrics": True,
        "icu": True,
    },
    ("OBSTETRIC", "LOW"): {
        "emergency": True,
        "obstetrics": True,
        "surgery": "preferred",
    },
    ("OBSTETRIC", "MEDIUM"): {
        "emergency": True,
        "obstetrics": True,
        "surgery": "preferred",
    },
    ("OBSTETRIC", "HIGH"): {
        "emergency": True,
        "obstetrics": True,
        "surgery": "preferred",
    },
    ("GENERAL_CRITICAL", "LOW"): {
        "emergency": True,
        "icu": False,
    },
    ("GENERAL_CRITICAL", "MEDIUM"): {
        "emergency": True,
        "icu": False,
    },
    ("GENERAL_CRITICAL", "HIGH"): {
        "emergency": True,
        "icu": True,
    },
}


@pytest.mark.parametrize(
    ("emergency_type", "severity", "expected"),
    [(etype, sev, EXPECTED[(etype, sev)]) for etype in EMERGENCY_TYPES for sev in SEVERITIES],
)
def test_required_capabilities_match_expected(emergency_type, severity, expected):
    assert get_required_capabilities(emergency_type, severity) == expected


@pytest.mark.parametrize("emergency_type", EMERGENCY_TYPES)
@pytest.mark.parametrize("severity", SEVERITIES)
def test_emergency_is_hard_required_for_every_type(emergency_type, severity):
    result = get_required_capabilities(emergency_type, severity)
    assert result["emergency"] is True


@pytest.mark.parametrize("severity", SEVERITIES)
def test_stroke_neurology_is_preferred_not_hard(severity):
    result = get_required_capabilities("STROKE", severity)
    assert result["neurology"] == "preferred"
    assert result["ct"] is True


@pytest.mark.parametrize(
    ("severity", "expected_cath_lab"),
    [("LOW", "preferred"), ("MEDIUM", True), ("HIGH", True)],
)
def test_car_diac_cath_lab_preferred_only_for_low(severity, expected_cath_lab):
    result = get_required_capabilities("CARDIAC", severity)
    assert result["cath_lab"] == expected_cath_lab


@pytest.mark.parametrize("severity", SEVERITIES)
def test_obstetric_surgery_is_preferred_not_hard(severity):
    result = get_required_capabilities("OBSTETRIC", severity)
    assert result["obstetrics"] is True
    assert result["surgery"] == "preferred"
    assert "icu" not in result


@pytest.mark.parametrize(
    "emergency_type",
    [etype for etype in EMERGENCY_TYPES if etype != "OBSTETRIC"],
)
def test_icu_hard_required_only_at_high_severity(emergency_type):
    assert get_required_capabilities(emergency_type, "LOW")["icu"] is False
    assert get_required_capabilities(emergency_type, "MEDIUM")["icu"] is False
    assert get_required_capabilities(emergency_type, "HIGH")["icu"] is True


def test_unknown_emergency_type_raises():
    with pytest.raises(ValueError):
        get_required_capabilities("UNKNOWN", "HIGH")


def test_unknown_severity_raises():
    with pytest.raises(ValueError):
        get_required_capabilities("TRAUMA", "CRITICAL")


def test_returns_fresh_dict_each_call():
    first = get_required_capabilities("TRAUMA", "HIGH")
    second = get_required_capabilities("TRAUMA", "HIGH")
    assert first == second
    assert first is not second
