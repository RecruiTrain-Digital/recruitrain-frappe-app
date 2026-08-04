# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.industry_validator
===================================================

Normalization and Validation for Industry master records.
"""

from __future__ import annotations

import re
from typing import Any

import frappe

from recruitrain_employer.utils.constants import DOCTYPE_INDUSTRY
from recruitrain_employer.utils.exceptions import ATSValidationError

#: Canonical default production industry master records
DEFAULT_PRODUCTION_INDUSTRIES: tuple[str, ...] = (
    "Information Technology",
    "Healthcare",
    "Automotive",
    "Manufacturing",
    "Financial Services",
    "Education",
    "Retail",
    "Construction",
    "Logistics",
    "Hospitality",
    "Energy",
    "Telecommunications",
)

#: Common domain synonyms / alias mapping -> canonical master name
INDUSTRY_SYNONYM_MAP: dict[str, str] = {
    "it": "Information Technology",
    "software": "Information Technology",
    "tech": "Information Technology",
    "healthcare": "Healthcare",
    "health care": "Healthcare",
    "medicine": "Healthcare",
    "automotive": "Automotive",
    "auto": "Automotive",
    "manufacturing": "Manufacturing",
    "finance": "Financial Services",
    "banking": "Financial Services",
    "financial services": "Financial Services",
    "education": "Education",
    "retail": "Retail",
    "e-commerce": "Retail",
    "ecommerce": "Retail",
    "construction": "Construction",
    "logistics": "Logistics",
    "transportation": "Logistics",
    "hospitality": "Hospitality",
    "energy": "Energy",
    "telecommunications": "Telecommunications",
    "telecom": "Telecommunications",
}


def normalize_industry_string(s: str) -> str:
    """Normalize string by replacing hyphens, underscores with spaces, collapsing whitespace, and lowercasing."""
    if not s:
        return ""
    cleaned = re.sub(r"[-_]+", " ", str(s))
    return " ".join(cleaned.split()).lower()


def seed_default_industries() -> list[str]:
    """Ensure default production industry master records exist in the database."""
    existing = frappe.get_all(DOCTYPE_INDUSTRY, fields=["name", "industry_name"])
    existing_names = {r.get("name") for r in existing if r.get("name")} | {
        r.get("industry_name") for r in existing if r.get("industry_name")
    }

    for ind in DEFAULT_PRODUCTION_INDUSTRIES:
        if ind not in existing_names:
            try:
                doc = frappe.new_doc(DOCTYPE_INDUSTRY)
                if doc.meta.has_field("industry_name"):
                    doc.industry_name = ind
                else:
                    doc.name = ind
                if doc.meta.has_field("is_active"):
                    doc.is_active = 1
                doc.insert(ignore_permissions=True)
            except Exception as exc:
                frappe.logger().error(f"Failed to create default Industry '{ind}': {exc}")

    all_recs = frappe.get_all(DOCTYPE_INDUSTRY, fields=["name"])
    return [r["name"] for r in all_recs]


def get_canonical_industry(raw_value: str) -> str:
    """Normalize raw industry input and resolve to canonical master record name."""
    if not raw_value or not str(raw_value).strip():
        return ""

    raw_str = str(raw_value).strip()
    norm_input = normalize_industry_string(raw_str)

    records = frappe.get_all(
        DOCTYPE_INDUSTRY,
        fields=["name", "industry_name"],
    )

    if not records:
        seed_default_industries()
        records = frappe.get_all(DOCTYPE_INDUSTRY, fields=["name", "industry_name"])

    existing_master_names = {r.get("name") for r in records if r.get("name")} | {
        r.get("industry_name") for r in records if r.get("industry_name")
    }
    if not any(i in existing_master_names for i in DEFAULT_PRODUCTION_INDUSTRIES):
        seed_default_industries()
        records = frappe.get_all(DOCTYPE_INDUSTRY, fields=["name", "industry_name"])

    norm_map: dict[str, str] = {}
    for r in records:
        canonical_name = r.get("industry_name") or r.get("name")
        if canonical_name:
            norm_key = normalize_industry_string(canonical_name)
            norm_map[norm_key] = canonical_name

    if norm_input in norm_map:
        return norm_map[norm_input]

    synonym_target = INDUSTRY_SYNONYM_MAP.get(norm_input)
    if synonym_target:
        norm_syn = normalize_industry_string(synonym_target)
        if norm_syn in norm_map:
            return norm_map[norm_syn]
        seed_default_industries()
        records = frappe.get_all(DOCTYPE_INDUSTRY, fields=["name", "industry_name"])
        norm_map = {
            normalize_industry_string(r.get("industry_name") or r.get("name")): (
                r.get("industry_name") or r.get("name")
            )
            for r in records
        }
        if norm_syn in norm_map:
            return norm_map[norm_syn]

    for r in records:
        canonical_name = r.get("industry_name") or r.get("name")
        if canonical_name and canonical_name.strip().lower() == raw_str.lower():
            return canonical_name

    raise ATSValidationError(
        f"Industry '{raw_str}' does not exist.",
        field="industry",
        details={"industry": raw_str},
    )


def validate_and_normalize_industry(data: dict | str) -> str | None:
    """Validate and normalize Industry in a payload dictionary or raw string."""
    if isinstance(data, dict):
        raw_val = data.get("industry")
        if not raw_val:
            return None
        canonical = get_canonical_industry(raw_val)
        data["industry"] = canonical
        return canonical
    elif isinstance(data, str):
        if not data.strip():
            return None
        return get_canonical_industry(data)
    return None
