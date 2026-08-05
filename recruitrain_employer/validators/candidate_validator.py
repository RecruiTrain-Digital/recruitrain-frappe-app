# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.candidate_validator
=====================================================

Input Validation & FSM Transition Layer for Candidate DocType Payloads.
"""

from __future__ import annotations

import re
from typing import Any
import frappe

from recruitrain_employer.normalizers.candidate_normalizer import normalize_candidate_payload
from recruitrain_employer.utils.constants import (
    ALLOWED_CANDIDATE_STATUSES,
    ALLOWED_DOCUMENT_TYPES,
    CANDIDATE_REQUIRED_FIELDS,
    CANDIDATE_STATUS_TRANSITIONS,
    MAX_FILE_SIZE_BYTES,
    MAX_FILE_SIZE_MB,
)
from recruitrain_employer.utils.exceptions import ATSValidationError
from recruitrain_employer.validators.employment_type_validator import (
    validate_and_normalize_employment_type_field,
)
from recruitrain_employer.validators.profession_validator import (
    validate_and_normalize_profession,
)

# Allowed creatable fields
CANDIDATE_CREATABLE_FIELDS: frozenset[str] = frozenset(
    [
        "company",
        "candidate_id",
        "candidate_name",
        "first_name",
        "middle_name",
        "last_name",
        "date_of_birth",
        "gender",
        "nationality",
        "marital_status",
        "email",
        "mobile_no",
        "phone",
        "mobile_number",
        "alternate_mobile",
        "linkedin",
        "linkedin_url",
        "portfolio",
        "portfolio_url",
        "github",
        "current_job_title",
        "current_company",
        "years_of_experience",
        "experience",
        "total_experience_years",
        "notice_period",
        "current_salary",
        "expected_salary",
        "salary",
        "preferred_location",
        "current_location",
        "location",
        "employment_type",
        "profession",
        "address_line_1",
        "address_line_2",
        "city",
        "state",
        "country",
        "postal_code",
        "status",
        "source",
        "resume",
        "profile_completion",
        "passport_number",
        "passport_expiry",
        "visa_status",
        "work_permit",
        "education",
        "experience",
        "skills",
        "languages",
        "certifications",
        "documents",
    ]
)

CANDIDATE_UPDATABLE_FIELDS: frozenset[str] = CANDIDATE_CREATABLE_FIELDS - {"email"}

_PHONE_RE: re.Pattern = re.compile(r"^\+?\d{7,15}$")
_PHONE_STRIP_RE: re.Pattern = re.compile(r"[\s\-().]")
_URL_RE: re.Pattern = re.compile(r"^https?://", re.IGNORECASE)


class CandidateValidator:
    """Stateless validator for Candidate create, update, and lifecycle state payloads."""

    def validate_create(self, data: dict[str, Any]) -> dict[str, Any]:
        """Normalize and validate a Candidate create payload.

        Returns normalized dictionary.
        """
        norm_data = normalize_candidate_payload(data)

        self.validate_required_fields(norm_data, CANDIDATE_REQUIRED_FIELDS)
        self.validate_email(norm_data["email"])

        if norm_data.get("mobile_no"):
            self.validate_phone(norm_data["mobile_no"])

        if norm_data.get("linkedin"):
            self._validate_url(norm_data["linkedin"], field="linkedin")

        if norm_data.get("portfolio"):
            self._validate_url(norm_data["portfolio"], field="portfolio")

        # Validate master links
        self.validate_master_links(norm_data)

        # Validate status if provided
        if norm_data.get("status"):
            self.validate_status_value(norm_data["status"])

        return norm_data

    def validate_update(self, data: dict[str, Any]) -> dict[str, Any]:
        """Normalize and validate a Candidate update payload."""
        if not data:
            raise ATSValidationError(
                "No update fields were provided. Please supply at least one field to update."
            )

        norm_data = normalize_candidate_payload(data)

        disallowed = set(norm_data.keys()) - CANDIDATE_UPDATABLE_FIELDS
        if disallowed:
            raise ATSValidationError(
                f"The following fields cannot be updated via this endpoint: {', '.join(sorted(disallowed))}.",
                details={"disallowed_fields": sorted(disallowed)},
            )

        if norm_data.get("mobile_no"):
            self.validate_phone(norm_data["mobile_no"])

        if norm_data.get("linkedin"):
            self._validate_url(norm_data["linkedin"], field="linkedin")

        if norm_data.get("portfolio"):
            self._validate_url(norm_data["portfolio"], field="portfolio")

        self.validate_master_links(norm_data)

        if norm_data.get("status"):
            self.validate_status_value(norm_data["status"])

        return norm_data

    def validate_status_transition(self, current_status: str, new_status: str) -> None:
        """Assert that a candidate status transition from current_status to new_status is legal."""
        self.validate_status_value(new_status)
        if current_status == new_status:
            return

        allowed = CANDIDATE_STATUS_TRANSITIONS.get(current_status, [])
        if new_status not in allowed:
            raise ATSValidationError(
                f"Illegal candidate status transition from '{current_status}' to '{new_status}'. "
                f"Allowed target status(es): {', '.join(allowed) if allowed else 'None (Terminal State)'}.",
                details={"current_status": current_status, "new_status": new_status, "allowed": allowed},
            )

    def validate_status_value(self, status: str) -> None:
        """Validate candidate status string against allowed values."""
        if status not in ALLOWED_CANDIDATE_STATUSES:
            raise ATSValidationError(
                f"Invalid candidate status '{status}'. Must be one of: {', '.join(ALLOWED_CANDIDATE_STATUSES)}.",
                field="status",
            )

    def validate_master_links(self, data: dict[str, Any]) -> None:
        """Validate & normalize master link references in payload."""
        # 1. Employment Type
        if data.get("employment_type"):
            norm_et = validate_and_normalize_employment_type_field(data["employment_type"])
            if norm_et:
                data["employment_type"] = norm_et

        # 2. Profession
        if data.get("profession"):
            norm_prof = validate_and_normalize_profession(data["profession"])
            if norm_prof:
                data["profession"] = norm_prof

        # 3. Country / Nationality Link existence checks
        for country_field in ("country", "nationality"):
            c_val = data.get(country_field)
            if c_val and frappe.db.exists("Country", c_val) is None:
                # Try title case lookup
                tc_c_val = str(c_val).title()
                if frappe.db.exists("Country", tc_c_val):
                    data[country_field] = tc_c_val

    @staticmethod
    def normalize_email(email: str) -> str:
        return email.strip().lower()

    @staticmethod
    def normalize_phone(phone: str) -> str:
        return _PHONE_STRIP_RE.sub("", phone.strip())

    def validate_required_fields(self, data: dict, required_fields: list[str]) -> None:
        missing = [
            field for field in required_fields if not str(data.get(field, "")).strip()
        ]
        if missing:
            raise ATSValidationError(
                f"The following required fields are missing or empty: {', '.join(missing)}.",
                details={"missing_fields": missing},
            )

    def validate_email(self, email: str) -> None:
        if not frappe.utils.validate_email_address(email):
            raise ATSValidationError(
                f"'{email}' is not a valid email address.",
                field="email",
            )

    def validate_phone(self, phone: str) -> None:
        if not _PHONE_RE.match(phone):
            raise ATSValidationError(
                f"'{phone}' is not a valid phone number. Please use international format (e.g. +19876543210).",
                field="mobile_no",
            )

    def _validate_url(self, url: str, field: str) -> None:
        if not _URL_RE.match(url.strip()):
            raise ATSValidationError(
                f"'{url}' is not a valid URL for field '{field}'. Must start with http:// or https://.",
                field=field,
            )

    def validate_languages(self, languages: list) -> None:
        if not isinstance(languages, list):
            raise ATSValidationError("Languages must be a list of objects.", field="languages")
        for idx, item in enumerate(languages):
            if not isinstance(item, dict):
                raise ATSValidationError(f"Language item at index {idx} must be an object.", field="languages")
            if not item.get("language") or not str(item.get("language")).strip():
                raise ATSValidationError(f"Language name is required at index {idx}.", field="languages")

    def validate_documents(self, documents: list) -> None:
        valid_types = {"Resume", "Passport", "Visa", "Driving License", "Certificate", "Other"}
        if not isinstance(documents, list):
            raise ATSValidationError("Documents must be a list of objects.", field="documents")
        for idx, item in enumerate(documents):
            if not isinstance(item, dict):
                raise ATSValidationError(f"Document item at index {idx} must be an object.", field="documents")
            dt = item.get("document_type")
            if dt and dt not in valid_types:
                raise ATSValidationError(
                    f"Invalid document_type '{dt}' at index {idx}. Must be one of: {', '.join(sorted(valid_types))}.",
                    field="documents",
                )

    def validate_education(self, education: list) -> None:
        if not isinstance(education, list):
            raise ATSValidationError("Education must be a list of objects.", field="education")
        for idx, item in enumerate(education):
            if not isinstance(item, dict):
                raise ATSValidationError(f"Education item at index {idx} must be an object.", field="education")
            if not item.get("institution") or not str(item.get("institution")).strip():
                raise ATSValidationError(f"Institution is required at index {idx}.", field="education")
            if not item.get("degree") or not str(item.get("degree")).strip():
                raise ATSValidationError(f"Degree is required at index {idx}.", field="education")

    def validate_experience(self, experience: list) -> None:
        if not isinstance(experience, list):
            raise ATSValidationError("Experience must be a list of objects.", field="experience")
        for idx, item in enumerate(experience):
            if not isinstance(item, dict):
                raise ATSValidationError(f"Experience item at index {idx} must be an object.", field="experience")
            if not item.get("company") or not str(item.get("company")).strip():
                raise ATSValidationError(f"Company is required at index {idx}.", field="experience")
            if not item.get("designation") or not str(item.get("designation")).strip():
                raise ATSValidationError(f"Designation is required at index {idx}.", field="experience")

    def validate_skills(self, skills: list) -> None:
        if not isinstance(skills, list):
            raise ATSValidationError("Skills must be a list of objects.", field="skills")
        for idx, item in enumerate(skills):
            if not isinstance(item, dict):
                raise ATSValidationError(f"Skill item at index {idx} must be an object.", field="skills")
            sname = item.get("skill")
            if not sname or not str(sname).strip():
                raise ATSValidationError(f"Skill name is required at index {idx}.", field="skills")
            sname = str(sname).strip()
            if not frappe.db.exists("Skill", sname):
                try:
                    sdoc = frappe.new_doc("Skill")
                    sdoc.skill_name = sname
                    sdoc.insert(ignore_permissions=True)
                except Exception:
                    pass

    def validate_certifications(self, certifications: list) -> None:
        if not isinstance(certifications, list):
            raise ATSValidationError("Certifications must be a list of objects.", field="certifications")
        for idx, item in enumerate(certifications):
            if not isinstance(item, dict):
                raise ATSValidationError(f"Certification item at index {idx} must be an object.", field="certifications")

    def validate_passport_and_visa(self, data: dict) -> None:
        if not isinstance(data, dict):
            raise ATSValidationError("Passport/Visa data must be a dictionary.")
        if data.get("passport_expiry"):
            exp = str(data["passport_expiry"]).strip()
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", exp):
                raise ATSValidationError(
                    f"'{exp}' is an invalid passport expiry date format. Expected YYYY-MM-DD.",
                    field="passport_expiry",
                )


def validate_document_upload(
    file_name: str,
    file_size_bytes: int,
    mime_type: str,
) -> None:
    """Validate candidate file attachment mime type and size limits."""
    if mime_type not in ALLOWED_DOCUMENT_TYPES:
        raise ATSValidationError(
            f"File type '{mime_type}' is not supported. Allowed types: PDF, DOC, DOCX.",
            details={"allowed_types": ALLOWED_DOCUMENT_TYPES},
        )
    if file_size_bytes > MAX_FILE_SIZE_BYTES:
        raise ATSValidationError(
            f"File size ({file_size_bytes / (1024*1024):.1f}MB) exceeds the maximum limit of {MAX_FILE_SIZE_MB}MB.",
            details={"max_size_mb": MAX_FILE_SIZE_MB},
        )
