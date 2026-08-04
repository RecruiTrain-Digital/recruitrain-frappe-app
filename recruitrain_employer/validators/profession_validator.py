# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.profession_validator
=====================================================

Normalization and Validation for Profession master records.

Objectives & Business Logic:
1. Normalize incoming Profession values (e.g. "Software Engineer", "Pflegefachkraft", "Nurse", "software developer" -> canonical master name).
2. Case-insensitive, space-insensitive, and hyphen-agnostic lookup against the Profession master DocType.
3. Synonym/alias resolution (e.g. "Krankenschwester" / "Krankenpfleger" -> "Pflegefachkraft", "Developer" -> "Software Engineer").
4. Automatically seed canonical default production Profession master records if missing.
5. Raise ATSValidationError (code="VALIDATION_ERROR") if no matching master record exists.
"""

from __future__ import annotations

import re
from typing import Any

import frappe

from recruitrain_employer.utils.constants import DOCTYPE_PROFESSION
from recruitrain_employer.utils.exceptions import ATSValidationError

#: Canonical default production profession master records
DEFAULT_PRODUCTION_PROFESSIONS: tuple[str, ...] = (
    "Software Engineer",
    "Frontend Developer",
    "Backend Developer",
    "Full Stack Developer",
    "DevOps Engineer",
    "Cloud Engineer",
    "Data Engineer",
    "Data Scientist",
    "QA Engineer",
    "Project Manager",
    "HR Manager",
    "Accountant",
    "Marketing Specialist",
    "Sales Executive",
    "Customer Support Executive",
    "Nurse",
    "Pflegefachkraft",
    "Physician",
    "Healthcare Assistant",
    "Warehouse Operator",
    "Electrician",
    "Mechanical Engineer",
    "Civil Engineer",
    "Architect",
    "Business Analyst",
    "UI UX Designer",
    "Product Manager",
)

#: Common domain synonyms / alias mapping -> canonical master name
PROFESSION_SYNONYM_MAP: dict[str, str] = {
    "pflegefachkraft": "Pflegefachkraft",
    "krankenpfleger": "Pflegefachkraft",
    "krankenschwester": "Pflegefachkraft",
    "altenpfleger": "Pflegefachkraft",
    "nurse": "Nurse",
    "registered nurse": "Nurse",
    "rn": "Nurse",
    "software engineer": "Software Engineer",
    "software developer": "Software Engineer",
    "programmer": "Software Engineer",
    "developer": "Software Engineer",
    "frontend developer": "Frontend Developer",
    "frontend engineer": "Frontend Developer",
    "react developer": "Frontend Developer",
    "backend developer": "Backend Developer",
    "backend engineer": "Backend Developer",
    "python developer": "Backend Developer",
    "node developer": "Backend Developer",
    "full stack developer": "Full Stack Developer",
    "fullstack developer": "Full Stack Developer",
    "fullstack engineer": "Full Stack Developer",
    "ui/ux designer": "UI UX Designer",
    "ui ux designer": "UI UX Designer",
    "ux designer": "UI UX Designer",
    "ui designer": "UI UX Designer",
    "product manager": "Product Manager",
    "product owner": "Product Manager",
    "project manager": "Project Manager",
    "pm": "Project Manager",
    "scrum master": "Project Manager",
    "qa engineer": "QA Engineer",
    "qa tester": "QA Engineer",
    "test engineer": "QA Engineer",
    "data scientist": "Data Scientist",
    "ai engineer": "Data Scientist",
    "ml engineer": "Data Scientist",
    "data engineer": "Data Engineer",
    "devops engineer": "DevOps Engineer",
    "devops": "DevOps Engineer",
    "sre": "DevOps Engineer",
    "cloud engineer": "Cloud Engineer",
    "aws engineer": "Cloud Engineer",
    "azure engineer": "Cloud Engineer",
    "physician": "Physician",
    "doctor": "Physician",
    "arzt": "Physician",
    "healthcare assistant": "Healthcare Assistant",
    "nursing assistant": "Healthcare Assistant",
    "pflegehelfer": "Healthcare Assistant",
    "hr manager": "HR Manager",
    "hr specialist": "HR Manager",
    "people manager": "HR Manager",
    "accountant": "Accountant",
    "financial accountant": "Accountant",
    "bookkeeper": "Accountant",
    "marketing specialist": "Marketing Specialist",
    "marketing manager": "Marketing Specialist",
    "sales executive": "Sales Executive",
    "sales representative": "Sales Executive",
    "account executive": "Sales Executive",
    "customer support executive": "Customer Support Executive",
    "support agent": "Customer Support Executive",
    "customer service representative": "Customer Support Executive",
    "warehouse operator": "Warehouse Operator",
    "warehouse worker": "Warehouse Operator",
    "logistics operator": "Warehouse Operator",
    "electrician": "Electrician",
    "elektroniker": "Electrician",
    "mechanical engineer": "Mechanical Engineer",
    "maschinenbauingenieur": "Mechanical Engineer",
    "civil engineer": "Civil Engineer",
    "bauingenieur": "Civil Engineer",
    "architect": "Architect",
    "architekt": "Architect",
    "business analyst": "Business Analyst",
    "ba": "Business Analyst",
}


def normalize_profession_string(s: str) -> str:
    """Normalize string by replacing hyphens, underscores, slashes with spaces, collapsing whitespace, and lowercasing."""
    if not s:
        return ""
    cleaned = re.sub(r"[-_/]+", " ", str(s))
    return " ".join(cleaned.split()).lower()


def seed_default_professions() -> list[str]:
    """Ensure default production profession master records exist in the database."""
    existing = frappe.get_all(DOCTYPE_PROFESSION, fields=["name", "profession_name"])
    existing_names = {r.get("name") for r in existing if r.get("name")} | {
        r.get("profession_name") for r in existing if r.get("profession_name")
    }

    for prof in DEFAULT_PRODUCTION_PROFESSIONS:
        if prof not in existing_names:
            try:
                doc = frappe.new_doc(DOCTYPE_PROFESSION)
                if doc.meta.has_field("profession_name"):
                    doc.profession_name = prof
                else:
                    doc.name = prof
                if doc.meta.has_field("is_active"):
                    doc.is_active = 1
                doc.insert(ignore_permissions=True)
            except Exception as exc:
                frappe.logger().error(f"Failed to create default Profession '{prof}': {exc}")

    all_recs = frappe.get_all(DOCTYPE_PROFESSION, fields=["name"])
    return [r["name"] for r in all_recs]


def get_canonical_profession(raw_value: str) -> str:
    """Normalize raw profession input and resolve to canonical master record name.

    Parameters
    ----------
    raw_value : str
        The raw profession string (e.g. "Software Engineer", "Pflegefachkraft", "Nurse", "software developer").

    Returns
    -------
    str
        The canonical profession string matching the database record.

    Raises
    ------
    ATSValidationError
        If no matching Profession record is found in the database.
    """
    if not raw_value or not str(raw_value).strip():
        return ""

    raw_str = str(raw_value).strip()
    norm_input = normalize_profession_string(raw_str)

    # 1. Fetch records from DB
    records = frappe.get_all(
        DOCTYPE_PROFESSION,
        fields=["name", "profession_name"],
    )

    # 2. Check if master table is empty or missing default production records
    if not records:
        seed_default_professions()
        records = frappe.get_all(DOCTYPE_PROFESSION, fields=["name", "profession_name"])

    existing_master_names = {r.get("name") for r in records if r.get("name")} | {
        r.get("profession_name") for r in records if r.get("profession_name")
    }
    if not any(p in existing_master_names for p in DEFAULT_PRODUCTION_PROFESSIONS):
        seed_default_professions()
        records = frappe.get_all(DOCTYPE_PROFESSION, fields=["name", "profession_name"])

    # 3. Build normalized lookup map: normalized_key -> canonical_name
    norm_map: dict[str, str] = {}
    for r in records:
        canonical_name = r.get("profession_name") or r.get("name")
        if canonical_name:
            norm_key = normalize_profession_string(canonical_name)
            norm_map[norm_key] = canonical_name

    # 4. Direct normalized match
    if norm_input in norm_map:
        return norm_map[norm_input]

    # 5. Synonym / Alias match
    synonym_target = PROFESSION_SYNONYM_MAP.get(norm_input)
    if synonym_target:
        norm_syn = normalize_profession_string(synonym_target)
        if norm_syn in norm_map:
            return norm_map[norm_syn]
        # Seed defaults if synonym target master record is missing
        seed_default_professions()
        records = frappe.get_all(DOCTYPE_PROFESSION, fields=["name", "profession_name"])
        norm_map = {
            normalize_profession_string(r.get("profession_name") or r.get("name")): (
                r.get("profession_name") or r.get("name")
            )
            for r in records
        }
        if norm_syn in norm_map:
            return norm_map[norm_syn]

    # 6. Case-insensitive exact comparison fallback
    for r in records:
        canonical_name = r.get("profession_name") or r.get("name")
        if canonical_name and canonical_name.strip().lower() == raw_str.lower():
            return canonical_name

    # 7. Validation error when no match exists
    raise ATSValidationError(
        f"Profession '{raw_str}' does not exist.",
        field="profession",
        details={"profession": raw_str},
    )


def validate_and_normalize_profession(data: dict | str) -> str | None:
    """Validate and normalize Profession in a payload dictionary or raw string.

    If a dict is passed, mutates data["profession"] to the canonical value.
    Returns the canonical value (or None if missing).
    """
    if isinstance(data, dict):
        raw_val = data.get("profession")
        if not raw_val:
            return None
        canonical = get_canonical_profession(raw_val)
        data["profession"] = canonical
        return canonical
    elif isinstance(data, str):
        if not data.strip():
            return None
        return get_canonical_profession(data)
    return None
