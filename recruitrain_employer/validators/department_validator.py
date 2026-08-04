# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.department_validator
=====================================================

Normalization and Validation for Department master records.

Objectives & Business Logic:
1. Normalize incoming Department values (e.g. "Healthcare", "healthcare", "HEALTH CARE", "Health-Care" -> "Healthcare").
2. Case-insensitive, space-insensitive, and hyphen-agnostic lookup against the Department master DocType.
3. Synonym/alias resolution (e.g. "Software" -> "Information Technology", "HR" -> "Human Resources", "Accounting" -> "Finance").
4. Automatically seed canonical default production Department master records if missing:
   - Information Technology
   - Engineering
   - Human Resources
   - Finance
   - Marketing
   - Sales
   - Healthcare
   - Operations
   - Administration
   - Legal
   - Customer Support
   - Research & Development
   - Manufacturing
   - Procurement
   - Quality Assurance
   - Logistics
5. Raise ATSValidationError (code="VALIDATION_ERROR") if no matching master record exists.
"""

from __future__ import annotations

import re
from typing import Any

import frappe

from recruitrain_employer.utils.constants import DOCTYPE_DEPARTMENT
from recruitrain_employer.utils.exceptions import ATSValidationError

#: Canonical default production department master records
DEFAULT_PRODUCTION_DEPARTMENTS: tuple[str, ...] = (
    "Information Technology",
    "Engineering",
    "Human Resources",
    "Finance",
    "Marketing",
    "Sales",
    "Healthcare",
    "Operations",
    "Administration",
    "Legal",
    "Customer Support",
    "Research & Development",
    "Manufacturing",
    "Procurement",
    "Quality Assurance",
    "Logistics",
)

#: Common domain synonyms / alias mapping -> canonical master name
DEPARTMENT_SYNONYM_MAP: dict[str, str] = {
    "it": "Information Technology",
    "information technology": "Information Technology",
    "software": "Information Technology",
    "software engineering": "Information Technology",
    "tech": "Information Technology",
    "technology": "Information Technology",
    "hr": "Human Resources",
    "human resources": "Human Resources",
    "personnel": "Human Resources",
    "finance": "Finance",
    "accounting": "Finance",
    "finance & accounting": "Finance",
    "finance and accounting": "Finance",
    "marketing": "Marketing",
    "sales & marketing": "Marketing",
    "sales and marketing": "Marketing",
    "advertising": "Marketing",
    "sales": "Sales",
    "business development": "Sales",
    "healthcare": "Healthcare",
    "healthcare services": "Healthcare",
    "health care": "Healthcare",
    "health care services": "Healthcare",
    "health": "Healthcare",
    "engineering": "Engineering",
    "dev": "Engineering",
    "development": "Engineering",
    "r&d": "Research & Development",
    "research & development": "Research & Development",
    "research and development": "Research & Development",
    "qa": "Quality Assurance",
    "quality assurance": "Quality Assurance",
    "testing": "Quality Assurance",
    "cs": "Customer Support",
    "customer support": "Customer Support",
    "support": "Customer Support",
    "customer service": "Customer Support",
    "ops": "Operations",
    "operations": "Operations",
    "admin": "Administration",
    "administration": "Administration",
    "legal": "Legal",
    "logistics": "Logistics",
    "supply chain": "Logistics",
    "procurement": "Procurement",
    "purchasing": "Procurement",
    "manufacturing": "Manufacturing",
}


def normalize_department_string(s: str) -> str:
    """Normalize string by replacing hyphens, underscores with spaces, collapsing whitespace, and lowercasing."""
    if not s:
        return ""
    cleaned = re.sub(r"[-_]+", " ", str(s))
    return " ".join(cleaned.split()).lower()


def seed_default_departments() -> list[str]:
    """Ensure default production department master records exist in the database."""
    existing = frappe.get_all(DOCTYPE_DEPARTMENT, fields=["name", "department_name"])
    existing_names = {r.get("name") for r in existing if r.get("name")} | {
        r.get("department_name") for r in existing if r.get("department_name")
    }

    for dept in DEFAULT_PRODUCTION_DEPARTMENTS:
        if dept not in existing_names:
            try:
                doc = frappe.new_doc(DOCTYPE_DEPARTMENT)
                if doc.meta.has_field("department_name"):
                    doc.department_name = dept
                else:
                    doc.name = dept
                if doc.meta.has_field("is_active"):
                    doc.is_active = 1
                doc.insert(ignore_permissions=True)
            except Exception as exc:
                frappe.logger().error(f"Failed to create default Department '{dept}': {exc}")

    all_recs = frappe.get_all(DOCTYPE_DEPARTMENT, fields=["name"])
    return [r["name"] for r in all_recs]


def get_canonical_department(raw_value: str) -> str:
    """Normalize raw department input and resolve to canonical master record name.

    Parameters
    ----------
    raw_value : str
        The raw department string (e.g. "Healthcare", "healthcare", "HEALTH CARE", "Health-Care", "Software", "engineering").

    Returns
    -------
    str
        The canonical department string matching the database record (e.g. "Healthcare", "Information Technology").

    Raises
    ------
    ATSValidationError
        If no matching Department record is found in the database.
    """
    if not raw_value or not str(raw_value).strip():
        return ""

    raw_str = str(raw_value).strip()
    norm_input = normalize_department_string(raw_str)

    # 1. Fetch records from DB
    records = frappe.get_all(
        DOCTYPE_DEPARTMENT,
        fields=["name", "department_name"],
    )

    # 2. Check if master table is empty or missing default production records
    if not records:
        seed_default_departments()
        records = frappe.get_all(DOCTYPE_DEPARTMENT, fields=["name", "department_name"])

    existing_master_names = {r.get("name") for r in records if r.get("name")} | {
        r.get("department_name") for r in records if r.get("department_name")
    }
    if not any(d in existing_master_names for d in DEFAULT_PRODUCTION_DEPARTMENTS):
        seed_default_departments()
        records = frappe.get_all(DOCTYPE_DEPARTMENT, fields=["name", "department_name"])

    # 3. Build normalized lookup map: normalized_key -> canonical_name
    norm_map: dict[str, str] = {}
    for r in records:
        canonical_name = r.get("department_name") or r.get("name")
        if canonical_name:
            norm_key = normalize_department_string(canonical_name)
            norm_map[norm_key] = canonical_name

    # 4. Direct normalized match
    if norm_input in norm_map:
        return norm_map[norm_input]

    # 5. Synonym / Alias match
    synonym_target = DEPARTMENT_SYNONYM_MAP.get(norm_input)
    if synonym_target:
        norm_syn = normalize_department_string(synonym_target)
        if norm_syn in norm_map:
            return norm_map[norm_syn]
        # Seed defaults if synonym target master record is missing
        seed_default_departments()
        records = frappe.get_all(DOCTYPE_DEPARTMENT, fields=["name", "department_name"])
        norm_map = {
            normalize_department_string(r.get("department_name") or r.get("name")): (
                r.get("department_name") or r.get("name")
            )
            for r in records
        }
        if norm_syn in norm_map:
            return norm_map[norm_syn]

    # 6. Case-insensitive exact comparison fallback
    for r in records:
        canonical_name = r.get("department_name") or r.get("name")
        if canonical_name and canonical_name.strip().lower() == raw_str.lower():
            return canonical_name

    # 7. Validation error when no match exists
    raise ATSValidationError(
        f"Department '{raw_str}' does not exist.",
        field="department",
        details={"department": raw_str},
    )


def validate_and_normalize_department(data: dict | str) -> str | None:
    """Validate and normalize Department in a payload dictionary or raw string.

    If a dict is passed, mutates data["department"] to the canonical value.
    Returns the canonical value (or None if missing).
    """
    if isinstance(data, dict):
        raw_val = data.get("department")
        if not raw_val:
            return None
        canonical = get_canonical_department(raw_val)
        data["department"] = canonical
        return canonical
    elif isinstance(data, str):
        if not data.strip():
            return None
        return get_canonical_department(data)
    return None
