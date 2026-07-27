"""
UAE tenant legal/billing profile — validation + field metadata (Phase 1).

Pure functions (no DB, no I/O) so they unit-test in isolation and run the same
checks the API and any importer rely on. The DB enforces the same enums via CHECK
constraints (migration 041); this layer gives friendly, early errors.

LEGAL: TRN / VAT / trade-licence handling is data modelling only, NOT a compliance
guarantee. Draft — requires review by a qualified UAE legal/tax professional before
production/customer use.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# The seven emirates (stored as stable snake_case codes; labels are a frontend concern).
EMIRATES: List[str] = [
    "abu_dhabi", "dubai", "sharjah", "ajman",
    "umm_al_quwain", "ras_al_khaimah", "fujairah",
]
JURISDICTIONS: List[str] = ["mainland", "free_zone"]
LANGUAGES: List[str] = ["en", "ar"]
PROCUREMENT_TYPES: List[str] = ["self_serve", "manual_invoice", "purchase_order"]

# Columns a tenant admin may set on their own profile. Order is the table order.
EDITABLE_FIELDS: List[str] = [
    "legal_name", "legal_name_ar", "trading_name", "trn", "trade_license_no",
    "emirate", "jurisdiction", "free_zone_name", "vat_registered",
    "registered_address", "billing_address", "currency", "timezone",
    "preferred_language", "industry_vertical", "store_count", "sku_count",
    "procurement_type", "billing_contact_name", "billing_contact_email",
    "billing_contact_phone", "finance_contact_name", "finance_contact_email",
    "finance_contact_phone",
]

_TRN_RE = re.compile(r"^\d{15}$")          # UAE TRN: exactly 15 digits
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")   # ISO 4217 shape (AED-first; GCC later)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_profile(payload: Dict[str, object]) -> Tuple[Optional[Dict[str, object]], Optional[str]]:
    """Validate a partial profile update. Returns (cleaned, None) on success or
    (None, error_message) on the first failure. Only keys present in the payload
    (and in EDITABLE_FIELDS) are returned — this supports partial PATCH-style saves.

    Empty strings are normalised to None so a cleared field stores NULL, not "".
    """
    cleaned: Dict[str, object] = {}

    for key, value in payload.items():
        if key not in EDITABLE_FIELDS:
            continue  # ignore unknown/non-editable keys (defensive)

        # Normalise blank strings to NULL.
        if isinstance(value, str):
            value = value.strip()
            if value == "":
                value = None

        if value is None:
            cleaned[key] = None
            continue

        if key == "trn":
            digits = re.sub(r"[\s-]", "", str(value))
            if not _TRN_RE.match(digits):
                return None, "TRN must be exactly 15 digits"
            cleaned[key] = digits
        elif key == "emirate":
            if value not in EMIRATES:
                return None, f"Invalid emirate. One of: {', '.join(EMIRATES)}"
            cleaned[key] = value
        elif key == "jurisdiction":
            if value not in JURISDICTIONS:
                return None, f"Invalid jurisdiction. One of: {', '.join(JURISDICTIONS)}"
            cleaned[key] = value
        elif key == "preferred_language":
            if value not in LANGUAGES:
                return None, f"Invalid language. One of: {', '.join(LANGUAGES)}"
            cleaned[key] = value
        elif key == "procurement_type":
            if value not in PROCUREMENT_TYPES:
                return None, f"Invalid procurement_type. One of: {', '.join(PROCUREMENT_TYPES)}"
            cleaned[key] = value
        elif key == "currency":
            up = str(value).upper()
            if not _CURRENCY_RE.match(up):
                return None, "Currency must be a 3-letter ISO code (e.g. AED)"
            cleaned[key] = up
        elif key == "vat_registered":
            cleaned[key] = bool(value)
        elif key in ("store_count", "sku_count"):
            try:
                n = int(value)
            except (TypeError, ValueError):
                return None, f"{key} must be a whole number"
            if n < 0:
                return None, f"{key} cannot be negative"
            cleaned[key] = n
        elif key in ("billing_contact_email", "finance_contact_email"):
            if not _EMAIL_RE.match(str(value)):
                return None, f"{key} is not a valid email address"
            cleaned[key] = str(value)
        else:
            cleaned[key] = str(value)

    return cleaned, None
