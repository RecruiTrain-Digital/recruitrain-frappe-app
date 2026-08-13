# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.serializers.candidate_serializer
======================================================

Centralized Output Serialization Layer for Candidate Subsystem.

Converts `Candidate` Frappe ORM document objects or SQL dictionary rows into
standardized API response dictionaries, appending computed attributes while
handling legacy aliases for migration backward-compatibility.
"""

from __future__ import annotations

from typing import Any
import frappe


def serialize_candidate(
    doc: Any,
    include_subresources: bool = True,
    latest_application: dict[str, Any] | None = None,
    include_legacy_aliases: bool = True,
) -> dict[str, Any]:
    """Serialize a Candidate document or dictionary into standard JSON payload.

    Parameters
    ----------
    doc : frappe.model.document.Document or dict
        Candidate ORM document or dictionary.
    include_subresources : bool, default True
        Whether to serialize child table sub-resources (education, skills, etc.).
    latest_application : dict or None
        Prefetched latest Job Application dict to attach to response.
    include_legacy_aliases : bool, default True
        Temporary backward-compatibility flag to attach frontend legacy aliases.

    Returns
    -------
    dict[str, Any]
        Standardized candidate JSON response.
    """
    if isinstance(doc, dict):
        d = doc
    else:
        d = doc.as_dict()

    # Compute full name
    first = d.get("first_name") or ""
    middle = d.get("middle_name") or ""
    last = d.get("last_name") or ""
    full_name = " ".join(filter(None, [first, middle, last])) or d.get("candidate_name") or d.get("name") or ""

    # Compute location display string
    city = d.get("city") or ""
    state = d.get("state") or ""
    country = d.get("country") or ""
    location_parts = [p for p in [city, state, country] if p]
    location_display = ", ".join(location_parts) if location_parts else d.get("preferred_location") or ""

    # Compute international candidate status
    nationality = (d.get("nationality") or "").lower()
    residence_country = (d.get("country") or "").lower()
    work_permit = bool(d.get("work_permit"))
    visa_status = d.get("visa_status")

    is_international = bool(
        (nationality and nationality != "india")
        or (residence_country and residence_country != "india")
        or (visa_status and visa_status != "Not Applicable")
        or work_permit
    )

    serialized: dict[str, Any] = {
        "name": d.get("name"),
        "candidate_id": d.get("candidate_id") or d.get("name"),
        "candidate_name": d.get("candidate_name") or d.get("name"),
        "company": d.get("company"),
        "first_name": d.get("first_name"),
        "middle_name": d.get("middle_name"),
        "last_name": d.get("last_name"),
        "full_name": full_name,
        "email": d.get("email"),
        "mobile_no": d.get("mobile_no"),
        "alternate_mobile": d.get("alternate_mobile"),
        "date_of_birth": str(d["date_of_birth"]) if d.get("date_of_birth") else None,
        "gender": d.get("gender"),
        "nationality": d.get("nationality"),
        "marital_status": d.get("marital_status"),
        "profession": d.get("profession"),
        "employment_type": d.get("employment_type"),
        "current_job_title": d.get("current_job_title"),
        "current_company": d.get("current_company"),
        "years_of_experience": d.get("years_of_experience", 0.0),
        "notice_period": d.get("notice_period", 0),
        "current_salary": d.get("current_salary"),
        "expected_salary": d.get("expected_salary"),
        "preferred_location": d.get("preferred_location"),
        "address_line_1": d.get("address_line_1"),
        "address_line_2": d.get("address_line_2"),
        "city": d.get("city"),
        "state": d.get("state"),
        "country": d.get("country"),
        "postal_code": d.get("postal_code"),
        "location_display": location_display,
        "status": d.get("status", "Active"),
        "source": d.get("source"),
        "resume": d.get("resume"),
        "profile_completion": float(d.get("profile_completion") or 0.0),
        "passport_number": d.get("passport_number"),
        "passport_expiry": str(d["passport_expiry"]) if d.get("passport_expiry") else None,
        "visa_status": d.get("visa_status"),
        "work_permit": work_permit,
        "is_international": is_international,
        "creation": str(d["creation"]) if d.get("creation") else None,
        "modified": str(d["modified"]) if d.get("modified") else None,
        "latest_application": latest_application,
    }

    # Include Sub-resources if loaded
    if include_subresources:
        serialized["education"] = [_clean_subresource(row) for row in d.get("education") or []]
        serialized["experience"] = [_clean_subresource(row) for row in d.get("experience") or []]
        serialized["skills"] = [_clean_subresource(row) for row in d.get("skills") or []]
        serialized["languages"] = [_clean_subresource(row) for row in d.get("languages") or []]
        serialized["certifications"] = [_clean_subresource(row) for row in d.get("certifications") or []]
        serialized["documents"] = [_clean_subresource(row) for row in d.get("documents") or []]

    # Include temporary legacy field aliases for transition period
    if include_legacy_aliases:
        serialized["phone"] = serialized["mobile_no"]
        serialized["mobile_number"] = serialized["mobile_no"]
        serialized["location"] = serialized["preferred_location"] or location_display
        serialized["salary"] = serialized["current_salary"]
        if "experience" not in serialized or not isinstance(serialized["experience"], list):
            serialized["experience"] = serialized["years_of_experience"]
        serialized["total_experience_years"] = serialized["years_of_experience"]

    return serialized


def _clean_subresource(row: Any) -> dict[str, Any]:
    """Clean internal Frappe metadata from child table dicts."""
    if not isinstance(row, dict):
        row = row.as_dict()
    cleaned = dict(row)
    for meta_key in ("doctype", "owner", "modified_by", "idx", "parent", "parentfield", "parenttype"):
        cleaned.pop(meta_key, None)
    return cleaned
