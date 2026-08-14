PREFERRED = "preferred"

SEVERITIES = ("LOW", "MEDIUM", "HIGH")

EMERGENCY_TYPES = (
    "TRAUMA",
    "STROKE",
    "CARDIAC",
    "RESPIRATORY",
    "BURN",
    "PEDIATRIC",
    "OBSTETRIC",
    "GENERAL_CRITICAL",
)


def get_required_capabilities(emergency_type: str, severity: str) -> dict:
    if severity not in SEVERITIES:
        raise ValueError(f"Unknown severity: {severity}")

    icu = {"icu": severity == "HIGH"}

    requirements = {
        "TRAUMA": {
            "emergency": True,
            "trauma": True,
            "surgery": True,
            "blood_bank": True,
            **icu,
        },
        "STROKE": {
            "emergency": True,
            "ct": True,
            "neurology": PREFERRED,
            **icu,
        },
        "CARDIAC": {
            "emergency": True,
            "cardiology": True,
            "cath_lab": True if severity in ("MEDIUM", "HIGH") else PREFERRED,
            **icu,
        },
        "RESPIRATORY": {
            "emergency": True,
            **icu,
        },
        "BURN": {
            "emergency": True,
            "surgery": True,
            **icu,
        },
        "PEDIATRIC": {
            "emergency": True,
            "pediatrics": True,
            **icu,
        },
        "OBSTETRIC": {
            "emergency": True,
            "obstetrics": True,
            "surgery": PREFERRED,
        },
        "GENERAL_CRITICAL": {
            "emergency": True,
            **icu,
        },
    }

    try:
        return dict(requirements[emergency_type])
    except KeyError:
        raise ValueError(f"Unknown emergency type: {emergency_type}") from None
