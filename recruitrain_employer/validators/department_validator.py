# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.department_validator
=====================================================

Department Resolver, Seeding, Normalization, and Validation.

Objectives & Business Logic:
1. Seed default canonical departments automatically if missing:
   - Engineering
   - Information Technology
   - Healthcare
   - Human Resources
   - Finance
   - Marketing
   - Sales
   - Operations
   - Administration
   - Legal
   - Customer Support
   - Research & Development
   - Procurement
   - Manufacturing
   - Logistics
   - Quality Assurance
2. Implement DepartmentResolver:
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

from recruitrain_employer.utils.constants import DOCTYPE_DEPARTMENT
from recruitrain_employer.utils.exceptions import ATSValidationError

#: Canonical default production department master records
DEFAULT_PRODUCTION_DEPARTMENTS: tuple[str, ...] = (
    "Engineering",
    "Information Technology",
    "Healthcare",
    "Human Resources",
    "Finance",
    "Marketing",
    "Sales",
    "Operations",
    "Administration",
    "Legal",
    "Customer Support",
    "Research & Development",
    "Procurement",
    "Manufacturing",
    "Logistics",
    "Quality Assurance",
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
    """Normalize string by replacing hyphens, underscores, slashes with spaces, collapsing whitespace, and lowercasing."""
    if not s:
        return ""
    cleaned = re.sub(r"[-_/]+", " ", str(s))
    return " ".join(cleaned.split()).lower()


def seed_default_departments() -> list[str]:
    """Ensure default production department master records exist in the database automatically."""
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
                if doc.meta.has_field("disabled"):
                    doc.disabled = 0
                if doc.meta.has_field("is_active"):
                    doc.is_active = 1
                doc.insert(ignore_permissions=True)
            except Exception as exc:
                frappe.logger().error(f"Failed to create default Department '{dept}': {exc}")

    all_recs = frappe.get_all(DOCTYPE_DEPARTMENT, fields=["name"])
    return [r["name"] for r in all_recs]


class DepartmentResolver:
    """Robust resolver for Department master records."""

    @classmethod
    def resolve(cls, raw_value: str) -> str:
        """Resolve raw input string to canonical database Department primary key name.

        Ignores case, hyphens, underscores, multiple spaces, and resolves synonyms.
        """
        if not raw_value or not str(raw_value).strip():
            return ""

        raw_str = str(raw_value).strip()
        norm_input = normalize_department_string(raw_str)

        # 1. Query existing records
        records = frappe.get_all(DOCTYPE_DEPARTMENT, fields=["name", "department_name"])

        # 2. Check if DB missing default production records
        existing_keys = {r.get("name") for r in records if r.get("name")} | {
            r.get("department_name") for r in records if r.get("department_name")
        }
        if not records or not any(d in existing_keys for d in DEFAULT_PRODUCTION_DEPARTMENTS):
            seed_default_departments()
            records = frappe.get_all(DOCTYPE_DEPARTMENT, fields=["name", "department_name"])

        # 3. Build lookup maps: normalized key -> canonical db name
        norm_map: dict[str, str] = {}
        for r in records:
            db_name = r.get("name")
            dept_label = r.get("department_name")
            if db_name:
                norm_map[normalize_department_string(db_name)] = db_name
            if dept_label:
                norm_map[normalize_department_string(dept_label)] = db_name

        # Direct normalized match
        if norm_input in norm_map:
            return norm_map[norm_input]

        # Synonym match
        synonym_target = DEPARTMENT_SYNONYM_MAP.get(norm_input)
        if synonym_target:
            norm_syn = normalize_department_string(synonym_target)
            if norm_syn in norm_map:
                return norm_map[norm_syn]
            # Retry after re-seeding
            seed_default_departments()
            records = frappe.get_all(DOCTYPE_DEPARTMENT, fields=["name", "department_name"])
            for r in records:
                db_name = r.get("name")
                dept_label = r.get("department_name")
                if db_name:
                    norm_map[normalize_department_string(db_name)] = db_name
                if dept_label:
                    norm_map[normalize_department_string(dept_label)] = db_name
            if norm_syn in norm_map:
                return norm_map[norm_syn]

        # Case-insensitive substring/exact fallback
        for r in records:
            db_name = r.get("name")
            dept_label = r.get("department_name")
            if db_name and db_name.strip().lower() == raw_str.lower():
                return db_name
            if dept_label and dept_label.strip().lower() == raw_str.lower():
                return db_name

        raise ATSValidationError(
            f"Department '{raw_str}' does not exist.",
            field="department",
            details={"department": raw_str},
        )


def get_canonical_department(raw_value: str) -> str:
    """Wrapper around DepartmentResolver.resolve for backward compatibility."""
    return DepartmentResolver.resolve(raw_value)


def validate_and_normalize_department(data: dict | str) -> str | None:
    """Validate and normalize Department in a payload dictionary or raw string."""
    if isinstance(data, dict):
        raw_val = data.get("department")
        if not raw_val:
            return None
        canonical = DepartmentResolver.resolve(raw_val)
        data["department"] = canonical
        return canonical
    elif isinstance(data, str):
        if not data.strip():
            return None
        return DepartmentResolver.resolve(data)
    return None
