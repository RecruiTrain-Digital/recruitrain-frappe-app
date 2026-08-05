# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.normalizers.candidate_normalizer
======================================================

Centralized Payload Normalization Layer for Candidate Subsystem.

Converts camelCase keys, legacy frontend field aliases, and dirty string inputs
into canonical snake_case backend parameters aligned with `Candidate` DocType schema.
"""

from __future__ import annotations

import re
from typing import Any

# Map of legacy/UI field aliases to canonical Candidate DocType field names
CANDIDATE_ALIAS_MAP: dict[str, str] = {
    "firstName": "first_name",
    "middleName": "middle_name",
    "lastName": "last_name",
    "dob": "date_of_birth",
    "dateOfBirth": "date_of_birth",
    "phone": "mobile_no",
    "mobileNumber": "mobile_no",
    "mobile": "mobile_no",
    "alternatePhone": "alternate_mobile",
    "alternateMobile": "alternate_mobile",
    "maritalStatus": "marital_status",
    "jobTitle": "current_job_title",
    "designation": "current_job_title",
    "currentJobTitle": "current_job_title",
    "companyName": "current_company",
    "currentCompany": "current_company",
    "experience": "years_of_experience",
    "yearsOfExperience": "years_of_experience",
    "totalExperienceYears": "years_of_experience",
    "noticePeriod": "notice_period",
    "salary": "current_salary",
    "currentSalary": "current_salary",
    "expectedSalary": "expected_salary",
    "location": "preferred_location",
    "preferredLocation": "preferred_location",
    "employmentType": "employment_type",
    "address1": "address_line_1",
    "addressLine1": "address_line_1",
    "address2": "address_line_2",
    "addressLine2": "address_line_2",
    "zip": "postal_code",
    "zipCode": "postal_code",
    "postalCode": "postal_code",
    "profileCompletion": "profile_completion",
    "passportNumber": "passport_number",
    "passportExpiry": "passport_expiry",
    "visaStatus": "visa_status",
    "workPermit": "work_permit",
}

# Sub-resource child table alias maps
EDUCATION_ALIAS_MAP: dict[str, str] = {
    "startDate": "start_date",
    "endDate": "end_date",
    "percentageCgpa": "percentage__cgpa",
    "percentage": "percentage__cgpa",
    "cgpa": "percentage__cgpa",
}

EXPERIENCE_ALIAS_MAP: dict[str, str] = {
    "startDate": "start_date",
    "endDate": "end_date",
    "currentCompany": "current_company",
    "employmentType": "employment_type",
}

SKILL_ALIAS_MAP: dict[str, str] = {
    "experienceYears": "experience_years",
    "yearsOfExperience": "experience_years",
}

CERTIFICATION_ALIAS_MAP: dict[str, str] = {
    "issuedBy": "issued_by",
    "issueDate": "issue_date",
    "expiryDate": "expiry_date",
    "credentialUrl": "credential_url",
}

DOCUMENT_ALIAS_MAP: dict[str, str] = {
    "documentType": "document_type",
}


def normalize_email_address(email: str | None) -> str | None:
    """Lowercase and strip whitespace from email addresses."""
    if not email:
        return None
    return str(email).strip().lower()


def normalize_phone_number(phone: str | None) -> str | None:
    """Strip cosmetic punctuation from phone numbers while preserving leading +."""
    if not phone:
        return None
    phone_str = str(phone).strip()
    # Strip spaces, hyphens, parentheses, dots
    cleaned = re.sub(r"[\s\-\(\)\.]", "", phone_str)
    return cleaned


def normalize_candidate_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw candidate payload dictionary into canonical backend schema.

    Parameters
    ----------
    data : dict[str, Any]
        Raw candidate dictionary (may contain camelCase or legacy keys).

    Returns
    -------
    dict[str, Any]
        Canonical snake_case payload ready for validation and ORM persistence.
    """
    if not isinstance(data, dict):
        return {}

    normalized: dict[str, Any] = {}

    # 1. Alias translation for top-level fields
    for key, value in data.items():
        canonical_key = CANDIDATE_ALIAS_MAP.get(key, key)
        normalized[canonical_key] = value

    # 2. Field-level string/numeric normalizations
    if "email" in normalized and isinstance(normalized["email"], str):
        normalized["email"] = normalize_email_address(normalized["email"])

    if "mobile_no" in normalized and normalized["mobile_no"]:
        normalized["mobile_no"] = normalize_phone_number(normalized["mobile_no"])

    if "alternate_mobile" in normalized and normalized["alternate_mobile"]:
        normalized["alternate_mobile"] = normalize_phone_number(normalized["alternate_mobile"])

    if "years_of_experience" in normalized and normalized["years_of_experience"] is not None:
        try:
            normalized["years_of_experience"] = float(normalized["years_of_experience"])
        except (ValueError, TypeError):
            pass

    if "notice_period" in normalized and normalized["notice_period"] is not None:
        try:
            normalized["notice_period"] = int(normalized["notice_period"])
        except (ValueError, TypeError):
            pass

    if "work_permit" in normalized:
        normalized["work_permit"] = 1 if normalized["work_permit"] in (True, 1, "1", "true", "True") else 0

    # 3. Normalize Child Tables if present
    if "education" in normalized and isinstance(normalized["education"], list):
        normalized["education"] = [
            _normalize_child_row(item, EDUCATION_ALIAS_MAP) for item in normalized["education"] if isinstance(item, dict)
        ]

    if "experience" in normalized and isinstance(normalized["experience"], list):
        normalized["experience"] = [
            _normalize_child_row(item, EXPERIENCE_ALIAS_MAP) for item in normalized["experience"] if isinstance(item, dict)
        ]

    if "skills" in normalized and isinstance(normalized["skills"], list):
        normalized["skills"] = [
            _normalize_child_row(item, SKILL_ALIAS_MAP) for item in normalized["skills"] if isinstance(item, dict)
        ]

    if "certifications" in normalized and isinstance(normalized["certifications"], list):
        normalized["certifications"] = [
            _normalize_child_row(item, CERTIFICATION_ALIAS_MAP) for item in normalized["certifications"] if isinstance(item, dict)
        ]

    if "documents" in normalized and isinstance(normalized["documents"], list):
        normalized["documents"] = [
            _normalize_child_row(item, DOCUMENT_ALIAS_MAP) for item in normalized["documents"] if isinstance(item, dict)
        ]

    return normalized


def _normalize_child_row(item: dict[str, Any], alias_map: dict[str, str]) -> dict[str, Any]:
    """Helper to map keys in a child table dictionary."""
    row: dict[str, Any] = {}
    for k, v in item.items():
        canonical_k = alias_map.get(k, k)
        row[canonical_k] = v
    return row
