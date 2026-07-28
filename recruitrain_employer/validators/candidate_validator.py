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
        "first_name",
        "last_name",
        "email",
        "phone",
        "date_of_birth",
        "gender",
        "nationality",
        "current_location",
        "profession",
        "bio",
        "linkedin_url",
        "portfolio_url",
        "status",
    ]
)

#: Fields a caller may modify on an existing Candidate record.
#: Email is excluded — use the dedicated email-change flow (future sprint).
CANDIDATE_UPDATABLE_FIELDS: frozenset[str] = frozenset(
    [
        "first_name",
        "last_name",
        "phone",
        "date_of_birth",
        "gender",
        "nationality",
        "current_location",
        "profession",
        "bio",
        "linkedin_url",
        "portfolio_url",
        "status",
    ]
)

# ---------------------------------------------------------------------------
# Compiled Patterns
# ---------------------------------------------------------------------------

#: Post-normalization phone pattern.
#: After ``normalize_phone`` strips spaces, dashes, and parentheses, the
#: remaining string must be an optional leading ``+`` followed by 7–15 digits.
#: This is intentionally tighter than the previous pattern because normalization
#: has already removed all cosmetic punctuation.
_PHONE_RE: re.Pattern = re.compile(r"^\+?\d{7,15}$")

#: Characters to strip during phone normalization.
#: Parentheses, spaces, hyphens, and dots are cosmetic formatting only.
_PHONE_STRIP_RE: re.Pattern = re.compile(r"[\s\-().]")

#: URL scheme validation — must start with http:// or https://.
_URL_RE: re.Pattern = re.compile(r"^https?://", re.IGNORECASE)


class CandidateValidator:
    """Stateless validator for Candidate create and update payloads.

    Normalization is applied in-place on the ``data`` dict at the start of
    ``validate_create`` and ``validate_update``.  This means the service
    layer receives — and stores — the canonical form without any extra steps.

    Instantiated once per service call.  All methods are side-effect-free
    except for normalizing ``data`` in-place and raising ``ATSValidationError``
    on invalid input.

    Usage
    -----
    ::

        validator = CandidateValidator()
        validator.validate_create(data)   # normalizes + validates; raises on failure
        validator.validate_update(data)   # normalizes + validates; raises on failure
    """

    # ------------------------------------------------------------------
    # Top-Level Validators (called by CandidateService)
    # ------------------------------------------------------------------

    def validate_create(self, data: dict) -> None:
        """Normalize and validate a Candidate create payload.

        Normalization is applied **in-place** on ``data`` before any
        validation check runs.  The caller (``CandidateService``) therefore
        always receives canonical values and persists them to the database.

        Parameters
        ----------
        data : dict
            Raw input data from the API request.  Modified in-place to
            contain normalized ``email`` and ``phone`` values.

        Raises
        ------
        ATSValidationError
            If any required field is missing, empty, or has an invalid value
            after normalization.

        Checks Performed (in order)
        ---------------------------
        1. Normalize ``email`` (trim, lowercase) and write back to ``data``.
        2. Normalize ``phone`` (strip punctuation) if present; write back.
        3. All ``CANDIDATE_REQUIRED_FIELDS`` are present and non-empty.
        4. Normalized ``email`` format is valid.
        5. Normalized ``phone`` format is valid (if provided).
        6. ``linkedin_url`` and ``portfolio_url`` start with http(s):// (if provided).
        """
        # Normalize before validation so checks always see canonical values.
        if data.get("email"):
            data["email"] = self.normalize_email(data["email"])

        if data.get("phone"):
            data["phone"] = self.normalize_phone(data["phone"])

        self.validate_required_fields(data, CANDIDATE_REQUIRED_FIELDS)
        self.validate_email(data["email"])

        if data.get("phone"):
            self.validate_phone(data["phone"])

        if data.get("linkedin_url"):
            self._validate_url(data["linkedin_url"], field="linkedin_url")

        if data.get("portfolio_url"):
            self._validate_url(data["portfolio_url"], field="portfolio_url")

    def validate_update(self, data: dict) -> None:
        """Normalize and validate a Candidate update payload.

        Normalization is applied **in-place** on ``data`` before validation.

        Parameters
        ----------
        data : dict
            Partial Candidate fields from the API request.  Must be non-empty.
            Modified in-place to contain a normalized ``phone`` value if present.

        Raises
        ------
        ATSValidationError
            If ``data`` is empty, contains non-updatable fields, or any
            provided value is invalid after normalization.

        Checks Performed (in order)
        ---------------------------
        1. ``data`` contains at least one field (no-op updates are rejected).
        2. All keys in ``data`` are present in ``CANDIDATE_UPDATABLE_FIELDS``.
        3. Normalize ``phone`` (strip punctuation) if present; write back.
        4. Normalized ``phone`` format is valid (if provided).
        5. ``linkedin_url`` and ``portfolio_url`` start with http(s):// (if provided).

        Notes
        -----
        Email is intentionally excluded from updatable fields.  See module
        docstring for the email change policy.
        """
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

        # Normalize phone before validation.
        if data.get("phone"):
            data["phone"] = self.normalize_phone(data["phone"])
            self.validate_phone(data["phone"])

        if data.get("linkedin_url"):
            self._validate_url(data["linkedin_url"], field="linkedin_url")

        if data.get("portfolio_url"):
            self._validate_url(data["portfolio_url"], field="portfolio_url")

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
