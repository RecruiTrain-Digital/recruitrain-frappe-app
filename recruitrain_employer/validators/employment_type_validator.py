# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.employment_type_validator
===========================================================

Normalization and Validation for Employment Type master records.

Objectives & Business Logic:
1. Normalize incoming Employment Type values (e.g., "Full-time", "Full Time", "full time", "FULL_TIME" -> "Full Time").
2. Case-insensitive and hyphen/space-insensitive lookup against the Employment Type master DocType.
3. Synonym/alias resolution (e.g., "Contractual" -> "Contract", "Intern" -> "Internship").
4. If the Employment Type master is empty (or missing default production records), auto-create standard master records:
   - Full Time
   - Part Time
   - Contract
   - Internship
   - Temporary
   - Freelance
5. Raise ATSValidationError (code="VALIDATION_ERROR") if no matching master record exists.
"""

from __future__ import annotations

import re
from typing import Any

import frappe

from recruitrain_employer.utils.constants import DOCTYPE_EMPLOYMENT_TYPE
from recruitrain_employer.utils.exceptions import ATSValidationError

#: Canonical default production master records
DEFAULT_PRODUCTION_EMPLOYMENT_TYPES: tuple[str, ...] = (
    "Full Time",
    "Part Time",
    "Contract",
    "Internship",
    "Temporary",
    "Freelance",
)

#: Common domain synonyms / alias mapping -> canonical master name
SYNONYM_MAP: dict[str, str] = {
    "contractual": "Contract",
    "intern": "Internship",
    "freelancer": "Freelance",
    "temp": "Temporary",
    "fulltime": "Full Time",
    "parttime": "Part Time",
}


def normalize_employment_type_string(s: str) -> str:
    """Normalize string by replacing hyphens, underscores with spaces, collapsing whitespace, and lowercasing."""
    if not s:
        return ""
    cleaned = re.sub(r"[-_]+", " ", str(s))
    return " ".join(cleaned.split()).lower()


def seed_default_employment_types() -> list[str]:
    """Ensure default production employment type master records exist in the database."""
    existing = frappe.get_all(DOCTYPE_EMPLOYMENT_TYPE, fields=["name", "employment_type_name"])
    existing_names = {r.get("name") for r in existing if r.get("name")} | {
        r.get("employment_type_name") for r in existing if r.get("employment_type_name")
    }

    for et in DEFAULT_PRODUCTION_EMPLOYMENT_TYPES:
        if et not in existing_names:
            try:
                doc = frappe.new_doc(DOCTYPE_EMPLOYMENT_TYPE)
                doc.employment_type_name = et
                doc.is_active = 1
                doc.insert(ignore_permissions=True)
            except Exception as exc:
                frappe.logger().error(f"Failed to create default Employment Type '{et}': {exc}")

    all_recs = frappe.get_all(DOCTYPE_EMPLOYMENT_TYPE, fields=["name"])
    return [r["name"] for r in all_recs]


def get_canonical_employment_type(raw_value: str) -> str:
    """Normalize raw employment type input and resolve to canonical master record name.

    Parameters
    ----------
    raw_value : str
        The raw employment type string (e.g. "Full-time", "full time", "FULL_TIME", "Contractual").

    Returns
    -------
    str
        The canonical employment type string matching the database record (e.g. "Full Time").

    Raises
    ------
    ATSValidationError
        If no matching Employment Type record is found in the database.
    """
    if not raw_value or not str(raw_value).strip():
        return ""

    raw_str = str(raw_value).strip()
    norm_input = normalize_employment_type_string(raw_str)

    # 1. Fetch records from DB
    records = frappe.get_all(
        DOCTYPE_EMPLOYMENT_TYPE,
        filters={"is_active": 1},
        fields=["name", "employment_type_name"],
    )
    if not records:
        records = frappe.get_all(DOCTYPE_EMPLOYMENT_TYPE, fields=["name", "employment_type_name"])

    # 2. Check if master table is empty or missing default production records
    if not records:
        seed_default_employment_types()
        records = frappe.get_all(DOCTYPE_EMPLOYMENT_TYPE, fields=["name", "employment_type_name"])

    existing_master_names = {r.get("name") for r in records if r.get("name")}
    if not any(d in existing_master_names for d in DEFAULT_PRODUCTION_EMPLOYMENT_TYPES):
        seed_default_employment_types()
        records = frappe.get_all(DOCTYPE_EMPLOYMENT_TYPE, fields=["name", "employment_type_name"])

    # 3. Build normalized lookup map: normalized_key -> canonical_name
    norm_map: dict[str, str] = {}
    for r in records:
        canonical_name = r.get("employment_type_name") or r.get("name")
        if canonical_name:
            norm_key = normalize_employment_type_string(canonical_name)
            norm_map[norm_key] = canonical_name

    # 4. Direct normalized match
    if norm_input in norm_map:
        return norm_map[norm_input]

    # 5. Synonym / Alias match
    synonym_target = SYNONYM_MAP.get(norm_input)
    if synonym_target:
        norm_syn = normalize_employment_type_string(synonym_target)
        if norm_syn in norm_map:
            return norm_map[norm_syn]
        # Seed defaults if synonym target master record is missing
        seed_default_employment_types()
        records = frappe.get_all(DOCTYPE_EMPLOYMENT_TYPE, fields=["name", "employment_type_name"])
        norm_map = {
            normalize_employment_type_string(r.get("employment_type_name") or r.get("name")): (
                r.get("employment_type_name") or r.get("name")
            )
            for r in records
        }
        if norm_syn in norm_map:
            return norm_map[norm_syn]

    # 6. Case-insensitive exact comparison fallback
    for r in records:
        canonical_name = r.get("employment_type_name") or r.get("name")
        if canonical_name and canonical_name.strip().lower() == raw_str.lower():
            return canonical_name

    # 7. Validation error when no match exists
    raise ATSValidationError(
        f"Employment Type '{raw_str}' does not exist.",
        field="employment_type",
        details={"employment_type": raw_str},
    )


def validate_and_normalize_employment_type_field(data: dict | str) -> str | None:
    """Validate and normalize Employment Type in a payload dictionary or raw string.

    If a dict is passed, mutates data["employment_type"] to the canonical value.
    Returns the canonical value (or None if missing).
    """
    if isinstance(data, dict):
        raw_val = data.get("employment_type")
        if not raw_val:
            return None
        canonical = get_canonical_employment_type(raw_val)
        data["employment_type"] = canonical
        return canonical
    elif isinstance(data, str):
        if not data.strip():
            return None
        return get_canonical_employment_type(data)
    return None
