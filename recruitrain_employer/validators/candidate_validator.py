# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.candidate_validator
=====================================================

Input Validation for Candidate DocType Payloads.

Design Principles
-----------------
- All validation methods raise ``ATSValidationError`` on failure.
- No database reads are performed here except lightweight existence checks.
- The validator is fully independent of the API layer and can be unit-tested
  without a running Frappe instance — except for ``validate_email``, which
  delegates to ``frappe.utils.validate_email_address``.
- Methods are intentionally small and composable: ``validate_create`` and
  ``validate_update`` delegate to the atomic helpers below.

Normalization Rules
-------------------
Normalization is performed **before** validation so that both validation
and downstream storage operate on canonical forms:

**Email normalization** (``normalize_email``)
    1. Strip leading and trailing whitespace.
    2. Convert to lowercase.

    Rationale: ``" JANE@Company.COM "`` and ``"jane@company.com"`` are the
    same address.  Storing non-normalized emails causes duplicate records and
    broken uniqueness checks.  Normalization is applied in-place on the input
    ``data`` dict so the service layer automatically persists the canonical form.

**Phone normalization** (``normalize_phone``)
    Remove spaces, dashes, and parentheses (retaining the leading ``+`` and
    all digits).

    Rationale: ``"+91 98765-43210"``, ``"+91(98765)43210"``, and
    ``"+919876543210"`` are the same number.  Stripping cosmetic punctuation
    before validation ensures the regex runs on a consistent format and that
    the stored value is predictable for future search and deduplication.
    No external library is introduced.

Allowlisted Fields
------------------
``CANDIDATE_UPDATABLE_FIELDS`` defines which fields a caller may mutate
through the update endpoint.  System-managed fields (``name``, ``owner``,
``creation``, ``modified``, ``docstatus``) are never in this list.

Email Change Policy
-------------------
Email is intentionally excluded from ``CANDIDATE_UPDATABLE_FIELDS``.
Changing a candidate's email is a sensitive, verified operation that
requires a separate email-change flow (planned for a future sprint).
"""

from __future__ import annotations

import re

import frappe

from recruitrain_employer.utils.constants import (
    ALLOWED_DOCUMENT_TYPES,
    CANDIDATE_REQUIRED_FIELDS,
    MAX_FILE_SIZE_MB,
)
from recruitrain_employer.utils.exceptions import ATSValidationError


# ---------------------------------------------------------------------------
# Field Allowlists
# ---------------------------------------------------------------------------

#: Fields a caller may supply when creating a new Candidate.
CANDIDATE_CREATABLE_FIELDS: frozenset[str] = frozenset(
    [
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
        "bio",
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

#: Fields a caller may modify on an existing Candidate record.
#: Email is excluded — use the dedicated email-change flow (future sprint).
CANDIDATE_UPDATABLE_FIELDS: frozenset[str] = CANDIDATE_CREATABLE_FIELDS - {"email"}

# ---------------------------------------------------------------------------
# Compiled Patterns
# ---------------------------------------------------------------------------

#: Post-normalization phone pattern.
_PHONE_RE: re.Pattern = re.compile(r"^\+?\d{7,15}$")

#: Characters to strip during phone normalization.
_PHONE_STRIP_RE: re.Pattern = re.compile(r"[\s\-().]")

#: URL scheme validation — must start with http:// or https://.
_URL_RE: re.Pattern = re.compile(r"^https?://", re.IGNORECASE)


class CandidateValidator:
    """Stateless validator for Candidate create and update payloads."""

    # ------------------------------------------------------------------
    # Top-Level Validators (called by CandidateService)
    # ------------------------------------------------------------------

    def validate_create(self, data: dict) -> None:
        """Normalize and validate a Candidate create payload."""
        if data.get("email"):
            data["email"] = self.normalize_email(data["email"])

        phone_val = data.get("phone") or data.get("mobile_no") or data.get("mobile_number")
        if phone_val:
            norm_phone = self.normalize_phone(str(phone_val))
            data["mobile_no"] = norm_phone
            data["phone"] = norm_phone
            data["mobile_number"] = norm_phone

        self.validate_required_fields(data, CANDIDATE_REQUIRED_FIELDS)
        self.validate_email(data["email"])

        if data.get("mobile_no"):
            self.validate_phone(data["mobile_no"])

        link_url = data.get("linkedin_url") or data.get("linkedin")
        if link_url:
            self._validate_url(link_url, field="linkedin")

        port_url = data.get("portfolio_url") or data.get("portfolio")
        if port_url:
            self._validate_url(port_url, field="portfolio")

    def validate_update(self, data: dict) -> None:
        """Normalize and validate a Candidate update payload."""
        if not data:
            raise ATSValidationError(
                "No update fields were provided. "
                "Please supply at least one field to update."
            )

        disallowed = set(data.keys()) - CANDIDATE_UPDATABLE_FIELDS
        if disallowed:
            raise ATSValidationError(
                f"The following fields cannot be updated via this endpoint: "
                f"{', '.join(sorted(disallowed))}.",
                details={"disallowed_fields": sorted(disallowed)},
            )

        phone_val = data.get("phone") or data.get("mobile_no") or data.get("mobile_number")
        if phone_val:
            norm_phone = self.normalize_phone(str(phone_val))
            data["mobile_no"] = norm_phone
            data["phone"] = norm_phone
            data["mobile_number"] = norm_phone
            self.validate_phone(norm_phone)

        link_url = data.get("linkedin_url") or data.get("linkedin")
        if link_url:
            self._validate_url(link_url, field="linkedin")

        port_url = data.get("portfolio_url") or data.get("portfolio")
        if port_url:
            self._validate_url(port_url, field="portfolio")

    # ------------------------------------------------------------------
    # Normalization Methods (public so CandidateService can call directly)
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_email(email: str) -> str:
        """Return a canonical, lowercase, whitespace-stripped email address.

        Parameters
        ----------
        email : str
            Raw email address string from user input.

        Returns
        -------
        str
            The normalized email address.

        Examples
        --------
        ::

            normalize_email("  JANE@Company.COM  ")
            # → "jane@company.com"

        Notes
        -----
        Normalization happens before both validation and uniqueness checks.
        This prevents duplicate records caused by case or whitespace
        differences in user-supplied email addresses.
        """
        return email.strip().lower()

    @staticmethod
    def normalize_phone(phone: str) -> str:
        """Return a phone number with cosmetic punctuation stripped.

        Removes spaces, hyphens, parentheses, and dots while preserving
        a leading ``+`` sign and all digit characters.  No external library
        is introduced.

        Parameters
        ----------
        phone : str
            Raw phone number string from user input.

        Returns
        -------
        str
            The normalized phone number.

        Examples
        --------
        ::

            normalize_phone("+91 98765 43210")   # → "+919876543210"
            normalize_phone("+91-98765-43210")   # → "+919876543210"
            normalize_phone("(+91)9876543210")   # → "+919876543210"

        Notes
        -----
        Normalization removes purely cosmetic formatting so that the
        post-normalization regex (``_PHONE_RE``) can be tight and
        predictable.  The stored value is always the stripped form,
        which simplifies future deduplication and search.
        """
        return _PHONE_STRIP_RE.sub("", phone.strip())

    # ------------------------------------------------------------------
    # Atomic Validators (reusable across methods)
    # ------------------------------------------------------------------

    def validate_required_fields(self, data: dict, required_fields: list[str]) -> None:
        """Assert that all fields in ``required_fields`` are present and non-empty.

        Collects all missing fields before raising, so the caller receives a
        complete list in a single error rather than one field at a time.

        Parameters
        ----------
        data : dict
            The input payload to check.
        required_fields : list[str]
            Field names that must be present and have a truthy, non-whitespace value.

        Raises
        ------
        ATSValidationError
            Enumerating all missing or empty fields in the ``details`` payload.

        Example
        -------
        ::

            validator.validate_required_fields(
                {"first_name": "Jane"},
                ["first_name", "last_name", "email"]
            )
            # raises ATSValidationError listing last_name and email
        """
        missing = [
            field
            for field in required_fields
            if not str(data.get(field, "")).strip()
        ]
        if missing:
            raise ATSValidationError(
                f"The following required fields are missing or empty: "
                f"{', '.join(missing)}.",
                details={"missing_fields": missing},
            )

    def validate_email(self, email: str) -> None:
        """Assert that ``email`` is a well-formed email address.

        This method expects an already-normalized value (lowercase, stripped).
        Delegates to ``frappe.utils.validate_email_address``, which uses
        Python's ``email.utils`` module under the hood.

        Parameters
        ----------
        email : str
            Normalized email address string to validate.

        Raises
        ------
        ATSValidationError
            If the email address is not valid.
        """
        if not frappe.utils.validate_email_address(email):
            raise ATSValidationError(
                f"'{email}' is not a valid email address.",
                field="email",
            )

    def validate_phone(self, phone: str) -> None:
        """Assert that a normalized phone number matches the expected pattern.

        This method expects an already-normalized value (punctuation stripped
        by ``normalize_phone``).  The pattern therefore only needs to allow
        an optional leading ``+`` and 7–15 digits.

        Parameters
        ----------
        phone : str
            Normalized phone number string (output of ``normalize_phone``).

        Raises
        ------
        ATSValidationError
            If the normalized phone number does not match ``_PHONE_RE``.

        TODO: Integrate the ``phonenumbers`` library for strict country-code
              validation once additional dependencies are approved.
        """
        if not _PHONE_RE.match(phone):
            raise ATSValidationError(
                f"'{phone}' is not a valid phone number. "
                "Please use international format, e.g. +19876543210 "
                "or +91 98765 43210.",
                field="phone",
            )

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _validate_url(self, url: str, field: str) -> None:
        """Assert that ``url`` begins with ``http://`` or ``https://``.

        Parameters
        ----------
        url : str
            The URL string to validate.
        field : str
            The field name used in the error message for caller context.

        Raises
        ------
        ATSValidationError
            If the URL does not start with a recognised scheme.
        """
        if not _URL_RE.match(url.strip()):
            raise ATSValidationError(
                f"'{url}' is not a valid URL for field '{field}'. "
                "The URL must begin with http:// or https://.",
                field=field,
            )

    def validate_languages(self, languages: list) -> None:
        """Validate candidate languages payload list."""
        if not isinstance(languages, list):
            raise ATSValidationError("Languages must be a list of objects.", field="languages")
        for idx, item in enumerate(languages):
            if not isinstance(item, dict):
                raise ATSValidationError(f"Language item at index {idx} must be an object.", field="languages")
            if not item.get("language") or not str(item.get("language")).strip():
                raise ATSValidationError(f"Language name is required at index {idx}.", field="languages")

    def validate_documents(self, documents: list) -> None:
        """Validate candidate documents payload list."""
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
        """Validate candidate education payload list."""
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
        """Validate candidate experience payload list."""
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
        """Validate candidate skills payload list."""
        if not isinstance(skills, list):
            raise ATSValidationError("Skills must be a list of objects.", field="skills")
        for idx, item in enumerate(skills):
            if not isinstance(item, dict):
                raise ATSValidationError(f"Skill item at index {idx} must be an object.", field="skills")
            if not item.get("skill") or not str(item.get("skill")).strip():
                raise ATSValidationError(f"Skill name is required at index {idx}.", field="skills")

    def validate_certifications(self, certifications: list) -> None:
        """Validate candidate certifications payload list."""
        if not isinstance(certifications, list):
            raise ATSValidationError("Certifications must be a list of objects.", field="certifications")
        for idx, item in enumerate(certifications):
            if not isinstance(item, dict):
                raise ATSValidationError(f"Certification item at index {idx} must be an object.", field="certifications")

    def validate_passport_and_visa(self, data: dict) -> None:
        """Validate passport and visa fields."""
        if not isinstance(data, dict):
            raise ATSValidationError("Passport/Visa data must be a dictionary.")
        if data.get("passport_expiry"):
            exp = str(data["passport_expiry"]).strip()
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", exp):
                raise ATSValidationError(
                    f"'{exp}' is an invalid passport expiry date format. Expected YYYY-MM-DD.",
                    field="passport_expiry",
                )



# ---------------------------------------------------------------------------
# Document Upload Validation (Future Sprint)
# ---------------------------------------------------------------------------


def validate_document_upload(
    file_name: str,
    file_size_bytes: int,
    mime_type: str,
) -> None:
    """Validate a file before it is attached to a Candidate record.

    Parameters
    ----------
    file_name : str
        Original filename from the upload.
    file_size_bytes : int
        Size of the uploaded file in bytes.
    mime_type : str
        MIME type of the uploaded file.

    Raises
    ------
    ATSValidationError
        If the file type is not allowed or exceeds the size limit.

    TODO: Check mime_type against ALLOWED_DOCUMENT_TYPES constant.
    TODO: Check file_size_bytes <= MAX_FILE_SIZE_MB * 1024 * 1024.
    TODO: Implement fully in the Document Upload sprint.
    """
    pass
