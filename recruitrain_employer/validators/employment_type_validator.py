# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.employment_type_validator
===========================================================

Employment Type Resolver, Seeding, Normalization, and Validation.

Objectives & Business Logic:
1. Seed default canonical employment types automatically if missing.
2. Implement EmploymentTypeResolver:
   - Case-insensitive
   - Hyphen-agnostic
   - Underscore-agnostic
   - Multiple space agnostic
   - Synonym / alias resolution
   - Returns canonical DB record `name`
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
    "full-time": "Full Time",
    "full_time": "Full Time",
    "parttime": "Part Time",
    "part-time": "Part Time",
    "part_time": "Part Time",
}


def normalize_employment_type_string(s: str) -> str:
    """Normalize string by replacing hyphens, underscores, slashes with spaces, collapsing whitespace, and lowercasing."""
    if not s:
        return ""
    cleaned = re.sub(r"[-_/]+", " ", str(s))
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
                if doc.meta.has_field("employment_type_name"):
                    doc.employment_type_name = et
                else:
                    doc.name = et
                if doc.meta.has_field("is_active"):
                    doc.is_active = 1
                doc.insert(ignore_permissions=True)
            except Exception as exc:
                frappe.logger().error(f"Failed to create default Employment Type '{et}': {exc}")

    all_recs = frappe.get_all(DOCTYPE_EMPLOYMENT_TYPE, fields=["name"])
    return [r["name"] for r in all_recs]


class EmploymentTypeResolver:
    """Robust resolver for Employment Type master records."""

    @classmethod
    def resolve(cls, raw_value: str) -> str:
        """Resolve raw input string to canonical database Employment Type primary key name.

        Example:
        health-care / HEALTHCARE -> Healthcare
        Full-time / full_time -> Full Time
        """
        if not raw_value or not str(raw_value).strip():
            return ""

        raw_str = str(raw_value).strip()
        norm_input = normalize_employment_type_string(raw_str)

        # 1. Fetch records from DB
        records = frappe.get_all(DOCTYPE_EMPLOYMENT_TYPE, fields=["name", "employment_type_name"])

        # 2. Check if DB table missing default records
        existing_keys = {r.get("name") for r in records if r.get("name")} | {
            r.get("employment_type_name") for r in records if r.get("employment_type_name")
        }
        if not records or not any(et in existing_keys for et in DEFAULT_PRODUCTION_EMPLOYMENT_TYPES):
            seed_default_employment_types()
            records = frappe.get_all(DOCTYPE_EMPLOYMENT_TYPE, fields=["name", "employment_type_name"])

        # 3. Build lookup maps: normalized key -> canonical db name
        norm_map: dict[str, str] = {}
        for r in records:
            db_name = r.get("name")
            et_label = r.get("employment_type_name")
            if db_name:
                norm_map[normalize_employment_type_string(db_name)] = db_name
            if et_label:
                norm_map[normalize_employment_type_string(et_label)] = db_name

        # Direct normalized match
        if norm_input in norm_map:
            return norm_map[norm_input]

        # Synonym match
        synonym_target = SYNONYM_MAP.get(norm_input)
        if synonym_target:
            norm_syn = normalize_employment_type_string(synonym_target)
            if norm_syn in norm_map:
                return norm_map[norm_syn]
            # Retry after re-seeding
            seed_default_employment_types()
            records = frappe.get_all(DOCTYPE_EMPLOYMENT_TYPE, fields=["name", "employment_type_name"])
            for r in records:
                db_name = r.get("name")
                et_label = r.get("employment_type_name")
                if db_name:
                    norm_map[normalize_employment_type_string(db_name)] = db_name
                if et_label:
                    norm_map[normalize_employment_type_string(et_label)] = db_name
            if norm_syn in norm_map:
                return norm_map[norm_syn]

        # Case-insensitive exact comparison fallback
        for r in records:
            db_name = r.get("name")
            et_label = r.get("employment_type_name")
            if db_name and db_name.strip().lower() == raw_str.lower():
                return db_name
            if et_label and et_label.strip().lower() == raw_str.lower():
                return db_name

        raise ATSValidationError(
            f"Employment Type '{raw_str}' does not exist.",
            field="employment_type",
            details={"employment_type": raw_str},
        )


def get_canonical_employment_type(raw_value: str) -> str:
    """Wrapper around EmploymentTypeResolver.resolve for backward compatibility."""
    return EmploymentTypeResolver.resolve(raw_value)


def validate_and_normalize_employment_type_field(data: dict | str) -> str | None:
    """Validate and normalize Employment Type in a payload dictionary or raw string."""
    if isinstance(data, dict):
        raw_val = data.get("employment_type")
        if not raw_val:
            return None
        canonical = EmploymentTypeResolver.resolve(raw_val)
        data["employment_type"] = canonical
        return canonical
    elif isinstance(data, str):
        if not data.strip():
            return None
        return EmploymentTypeResolver.resolve(data)
    return None
