"""Field mapping from ERP customer master to CRM account, with validation."""
import hashlib
import json
import re

REGION_TO_STATE = {
    "KA": "Karnataka", "MH": "Maharashtra", "TN": "Tamil Nadu", "GJ": "Gujarat",
    "DL": "Delhi", "TS": "Telangana", "UP": "Uttar Pradesh", "WB": "West Bengal",
}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)


class MappingError(ValueError):
    pass


def normalise_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return None
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10:
        raise MappingError(f"phone '{raw}' is not a valid 10-digit number")
    return f"+91 {digits[:5]} {digits[5:]}"


def erp_to_crm(c: dict) -> dict:
    name = " ".join((c.get("NAME1") or "").split())
    if not name:
        raise MappingError("NAME1 (customer name) is empty")
    state = REGION_TO_STATE.get(c.get("REGIO", ""))
    if not state:
        raise MappingError(f"unknown region code '{c.get('REGIO')}'")
    email = (c.get("SMTP_ADDR") or "").strip().lower() or None
    if email and not EMAIL_RE.match(email):
        raise MappingError(f"email '{email}' is invalid")
    return {
        "external_id": c["KUNNR"],
        "account_name": name,
        "billing_city": (c.get("ORT01") or "").strip().title(),
        "billing_state": state,
        "billing_country": "India" if c.get("LAND1", "IN") == "IN" else c["LAND1"],
        "email": email,
        "phone": normalise_phone(c.get("TELF1", "")),
        "credit_limit": float(c.get("KLIMK") or 0),
        "status": "On Hold" if c.get("SPERR") else "Active",
    }


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
