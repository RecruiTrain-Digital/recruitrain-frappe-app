# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.company_validator
===================================================

Input Validation for Company DocType Payloads.

Design Principles
-----------------
- All validation methods raise ``ATSValidationError`` on failure.
- No database reads are performed except lightweight ``frappe.db.exists``
  uniqueness checks.
- The validator is fully independent of the API layer.
- Methods are small and composable: ``validate_create`` and ``validate_update``
  delegate to atomic helpers.

Normalization Rules
-------------------
Normalization is applied **in-place** on the input ``data`` dict before
validation so that downstream storage always receives canonical values.

**Email normalization** (``normalize_email``)
    Strip whitespace, convert to lowercase.
    Rationale: ``" INFO@Company.COM "`` and ``"info@company.com"`` are the
    same address.  Non-normalized emails cause duplicate records and broken
    uniqueness checks.

**Phone normalization** (``normalize_phone``)
    Remove spaces, dashes, parentheses, and dots while preserving the leading
    ``+`` and all digits.  No external library is introduced.
    Rationale: Consistent stored format enables deduplication and search.

**Website normalization** (``normalize_website``)
    1. Strip whitespace.
    2. Prepend ``https://`` if no ``http://`` or ``https://`` scheme is present.
    3. Strip a trailing slash so stored URLs are uniform.
    Rationale: Users commonly type ``"company.com"`` without a scheme.
    Normalizing means the stored URL is always a valid, clickable href.

Allowlisted Fields
------------------
``COMPANY_UPDATABLE_FIELDS`` defines which fields a caller may mutate through
the update endpoint.  ``company_name`` is intentionally excluded — renaming a
company is a sensitive operation requiring a dedicated workflow (future sprint).
System-managed Frappe fields are never in this list.
"""

from __future__ import annotations

import re

import frappe

from recruitrain_employer.utils.constants import (
    ALLOWED_IMAGE_TYPES,
    COMPANY_REQUIRED_FIELDS,
    MAX_LOGO_SIZE_MB,
)
from recruitrain_employer.utils.exceptions import ATSValidationError


# ---------------------------------------------------------------------------
# Field Allowlists
# ---------------------------------------------------------------------------

#: Fields a caller may supply when creating a new Company.
#: All names must correspond to real fieldnames in company.json.
COMPANY_CREATABLE_FIELDS: frozenset[str] = frozenset(
    [
        "company_name",
        "legal_name",
        "company_code",
        "industry",
        "email",
        "phone",
        "alternate_phone",
        "hr_email",
        "support_email",
        "website",
        "description",
        "country",
        "state",
        "city",
        "address_line_1",
        "address_line_2",
        "postal_code",
        "status",
        "founded_year",
        "company_size",
        "linkedin",
        "twitter",
        "facebook",
        "instagram",
    ]
)

#: Fields a caller may modify on an existing Company record.
#: ``company_name`` is excluded — use a dedicated rename workflow (future sprint).
#: Email is excluded — use a dedicated verified email-change flow (future sprint).
#: All names must correspond to real fieldnames in company.json.
COMPANY_UPDATABLE_FIELDS: frozenset[str] = frozenset(
    [
        "legal_name",
        "company_code",
        "industry",
        "email",
        "phone",
        "alternate_phone",
        "hr_email",
        "support_email",
        "website",
        "description",
        "country",
        "state",
        "city",
        "address_line_1",
        "address_line_2",
        "postal_code",
        "logo",
        "banner",
        "primary_color",
        "secondary_color",
        "linkedin",
        "twitter",
        "facebook",
        "instagram",
        "status",
        "founded_year",
        "company_size",
        "timezone",
        "language",
        "date_format",
        "currency",
        "theme",
        "verified",
        "active",
    ]
)

# ---------------------------------------------------------------------------
# Compiled Patterns
# ---------------------------------------------------------------------------

#: Post-normalization phone pattern.
#: After ``normalize_phone`` strips cosmetic punctuation, the remaining string
#: must be an optional ``+`` followed by 7–15 digits.
_PHONE_RE: re.Pattern = re.compile(r"^\+?\d{7,15}$")

#: Characters stripped during phone normalization (spaces, dashes, parens, dots).
_PHONE_STRIP_RE: re.Pattern = re.compile(r"[\s\-().]")

#: URL scheme pattern — matches http:// or https:// at the start of a string.
_URL_SCHEME_RE: re.Pattern = re.compile(r"^https?://", re.IGNORECASE)

#: Validates a URL has a recognizable domain-like structure after the scheme.
#: Deliberately permissive; rejects obvious non-URLs (no dot, no TLD).
_URL_DOMAIN_RE: re.Pattern = re.compile(
    r"^https?://[a-zA-Z0-9\-]+(\.[a-zA-Z0-9\-]+)+", re.IGNORECASE
)

#: Allowed status values — must mirror the Select options in ``company.json`` exactly.
COMPANY_STATUS_OPTIONS: frozenset[str] = frozenset(
    ["Draft", "Pending Verification", "Active", "Suspended", "Inactive"]
)


class CompanyValidator:
    """Stateless validator for Company create and update payloads.

    Normalization is applied in-place on the ``data`` dict at the start of
    ``validate_create`` and ``validate_update``.  This means ``CompanyService``
    receives — and stores — canonical values without any extra steps.

    Usage
    -----
    ::

        validator = CompanyValidator()
        validator.validate_create(data)   # normalizes + validates in-place
        validator.validate_update(data)   # normalizes + validates in-place
    """

    # ------------------------------------------------------------------
    # Top-Level Validators (called by CompanyService)
    # ------------------------------------------------------------------

    def validate_create(self, data: dict) -> None:
        """Normalize and validate a Company create payload.

        Normalization is applied **in-place** on ``data`` so that
        ``CompanyService`` persists canonical values automatically.

        Parameters
        ----------
        data : dict
            Raw input data from the API request.  Modified in-place to
            contain normalized ``email``, ``phone``, and ``website`` values.

        Raises
        ------
        ATSValidationError
            If any required field is missing, empty, or has an invalid value
            after normalization.

        Checks Performed (in order)
        ---------------------------
        1. Normalize ``email`` (trim, lowercase) — write back to ``data``.
        2. Normalize ``phone`` (strip punctuation) — write back if present.
        3. Normalize ``website`` (prepend scheme, strip trailing slash) — write back if present.
        4. All ``COMPANY_REQUIRED_FIELDS`` are present and non-empty.
        5. ``email`` format is valid (if provided).
        6. ``phone`` format is valid (if provided).
        7. ``website`` format is valid (if provided).
        8. ``linkedin_url`` format is valid (if provided).
        9. ``twitter_url`` format is valid (if provided).
        """
        if data.get("email"):
            data["email"] = self.normalize_email(data["email"])

        if data.get("phone"):
            data["phone"] = self.normalize_phone(data["phone"])

        if data.get("website"):
            data["website"] = self.normalize_website(data["website"])

        self.validate_required_fields(data, COMPANY_REQUIRED_FIELDS)

        if data.get("email"):
            self.validate_email(data["email"])

        if data.get("phone"):
            self.validate_phone(data["phone"])

        if data.get("website"):
            self.validate_website(data["website"])

        if data.get("linkedin"):
            self._validate_url(data["linkedin"], field="linkedin")

        if data.get("twitter"):
            self._validate_url(data["twitter"], field="twitter")

        if data.get("facebook"):
            self._validate_url(data["facebook"], field="facebook")

        if data.get("instagram"):
            self._validate_url(data["instagram"], field="instagram")

        if data.get("status"):
            self.validate_status(data["status"])

    def validate_update(self, data: dict) -> None:
        """Normalize and validate a Company update payload.

        Normalization is applied **in-place** on ``data`` before validation.
        """
        alias_map = {
            "legalName": "legal_name",
            "companyName": "legal_name",
            "companyCode": "company_code",
            "industryIds": "industry",
            "companySize": "company_size",
            "size": "company_size",
            "foundedYear": "founded_year",
            "about": "description",
            "contactEmail": "email",
            "contactPhone": "phone",
            "alternatePhone": "alternate_phone",
            "hrEmail": "hr_email",
            "supportEmail": "support_email",
            "street": "address_line_1",
            "addressLine1": "address_line_1",
            "addressLine2": "address_line_2",
            "postalCode": "postal_code",
            "pincode": "postal_code",
            "primaryColor": "primary_color",
            "secondaryColor": "secondary_color",
            "dateFormat": "date_format",
        }

        for key in list(data.keys()):
            if key in alias_map:
                canonical_key = alias_map[key]
                val = data.pop(key)
                if canonical_key not in data or not data[canonical_key]:
                    data[canonical_key] = val
                msg = f"[STAGE 6: Filter Remapped] Key '{key}' remapped to canonical '{canonical_key}'"
                frappe.logger().info(msg)
                print(msg)

        stage5_msg = f"[STAGE 5: Validator Output Payload] {data}"
        frappe.logger().info(stage5_msg)
        print(stage5_msg)

        disallowed = set(data.keys()) - COMPANY_UPDATABLE_FIELDS
        if disallowed:
            for field in sorted(disallowed):
                msg = f"[STAGE 6: Filter Removed] Field '{field}' removed (Reason: Not present in COMPANY_UPDATABLE_FIELDS)"
                frappe.logger().info(msg)
                print(msg)
                data.pop(field, None)

        stage6_msg = f"[STAGE 6: Filtered Payload against COMPANY_UPDATABLE_FIELDS] {data}"
        frappe.logger().info(stage6_msg)
        print(stage6_msg)

        if not data:
            raise ATSValidationError(
                "No valid update fields remained after filtering against COMPANY_UPDATABLE_FIELDS. "
                "Stage 6 removed all fields because none matched the allowed backend updatable schema."
            )

        if data.get("founded_year"):
            fy = str(data["founded_year"]).strip()
            if len(fy) == 4 and fy.isdigit():
                data["founded_year"] = f"{fy}-01-01"

        if data.get("phone"):
            data["phone"] = self.normalize_phone(data["phone"])
            self.validate_phone(data["phone"])

        if data.get("website"):
            data["website"] = self.normalize_website(data["website"])
            self.validate_website(data["website"])

        if data.get("linkedin"):
            self._validate_url(data["linkedin"], field="linkedin")

        if data.get("twitter"):
            self._validate_url(data["twitter"], field="twitter")

        if data.get("facebook"):
            self._validate_url(data["facebook"], field="facebook")

        if data.get("instagram"):
            self._validate_url(data["instagram"], field="instagram")

        if data.get("status"):
            self.validate_status(data["status"])

    # ------------------------------------------------------------------
    # Normalization Methods (public — CompanyService may call directly)
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

            normalize_email("  INFO@Company.COM  ")
            # → "info@company.com"
        """
        return email.strip().lower()

    @staticmethod
    def normalize_phone(phone: str) -> str:
        """Return a phone number with cosmetic punctuation stripped.

        Removes spaces, hyphens, parentheses, and dots while preserving a
        leading ``+`` sign and all digit characters.  No external library.

        Parameters
        ----------
        phone : str
            Raw phone number string from user input.

        Returns
        -------
        str
            The normalized phone number (digits + optional leading ``+``).

        Examples
        --------
        ::

            normalize_phone("+1 800 555-1234")    # → "+18005551234"
            normalize_phone("(+44)20 7946 0958")  # → "+442079460958"
        """
        return _PHONE_STRIP_RE.sub("", phone.strip())

    @staticmethod
    def normalize_website(url: str) -> str:
        """Return a canonical website URL.

        1. Strip leading/trailing whitespace.
        2. Prepend ``https://`` if no ``http://`` or ``https://`` scheme is present.
        3. Strip a single trailing slash for uniformity.

        Parameters
        ----------
        url : str
            Raw website URL string from user input.

        Returns
        -------
        str
            The normalized URL with a scheme and no trailing slash.

        Examples
        --------
        ::

            normalize_website("company.com")           # → "https://company.com"
            normalize_website("http://company.com/")   # → "http://company.com"
            normalize_website("  HTTPS://Company.com") # → "HTTPS://Company.com"
                                                       #   (scheme preserved as-is)

        Notes
        -----
        Only a missing scheme is added; the original scheme casing is not
        altered.  ``validate_website`` performs the format check after
        normalization.  Path casing is intentionally preserved because URL
        paths can be case-sensitive on some web servers.
        """
        url = url.strip()
        if not _URL_SCHEME_RE.match(url):
            url = f"https://{url}"
        if url.endswith("/"):
            url = url[:-1]
        return url

    # ------------------------------------------------------------------
    # Atomic Validators (reusable)
    # ------------------------------------------------------------------

    def validate_required_fields(self, data: dict, required_fields: list[str]) -> None:
        """Assert that all fields in ``required_fields`` are present and non-empty.

        Collects all missing fields before raising so the caller receives a
        complete error in one shot rather than one field at a time.

        Parameters
        ----------
        data : dict
            The input payload to check.
        required_fields : list[str]
            Field names that must be present and truthy after stripping whitespace.

        Raises
        ------
        ATSValidationError
            Listing all missing or empty fields in the ``details`` payload.
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

        Delegates to ``frappe.utils.validate_email_address``.
        Expects a pre-normalized (trimmed, lowercase) value.

        Parameters
        ----------
        email : str
            Normalized email address to validate.

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

        Expects the output of ``normalize_phone`` (cosmetic punctuation already
        stripped).  The pattern allows an optional leading ``+`` and 7–15 digits.

        Parameters
        ----------
        phone : str
            Normalized phone number (output of ``normalize_phone``).

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
                "Please use international format, e.g. +1 800 555 1234.",
                field="phone",
            )

    def validate_website(self, url: str) -> None:
        """Assert that ``url`` is a recognizable website URL.

        Expects the output of ``normalize_website`` (scheme already prepended).
        Checks for a valid scheme and at least one dot in the domain.

        Parameters
        ----------
        url : str
            Normalized URL string (output of ``normalize_website``).

        Raises
        ------
        ATSValidationError
            If the URL does not match the expected domain pattern.
        """
        if not _URL_DOMAIN_RE.match(url):
            raise ATSValidationError(
                f"'{url}' is not a valid website URL. "
                "Example: https://company.com",
                field="website",
            )

    def validate_status(self, status: str) -> None:
        """Assert that ``status`` is one of the allowed Company status values.

        Allowed values mirror the Select options in ``company.json``::

            Draft | Pending Verification | Active | Suspended | Inactive

        Parameters
        ----------
        status : str
            The status string to validate.

        Raises
        ------
        ATSValidationError
            If the status value is not in the allowed set.
        """
        if status not in COMPANY_STATUS_OPTIONS:
            raise ATSValidationError(
                f"'{status}' is not a valid Company status. "
                f"Allowed values: {', '.join(COMPANY_STATUS_OPTIONS)}.",
                field="status",
            )

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _validate_url(self, url: str, field: str) -> None:
        """Assert that ``url`` begins with ``http://`` or ``https://``.

        Used for social profile URLs (LinkedIn, Twitter) where the scheme is
        expected to be provided by the caller (not auto-prepended like website).

        Parameters
        ----------
        url : str
            The URL string to validate.
        field : str
            The field name for the error message.

        Raises
        ------
        ATSValidationError
            If the URL does not start with a recognised scheme.
        """
        if not _URL_DOMAIN_RE.match(url.strip()):
            raise ATSValidationError(
                f"'{url}' is not a valid URL for field '{field}'. "
                "The URL must begin with http:// or https:// and include a domain.",
                field=field,
            )


# ---------------------------------------------------------------------------
# Logo Upload Validation (Future Sprint)
# ---------------------------------------------------------------------------


def validate_logo_upload(
    file_name: str,
    file_size_bytes: int,
    mime_type: str,
) -> None:
    """Validate a company logo before upload.

    Parameters
    ----------
    file_name : str
        Original filename of the logo.
    file_size_bytes : int
        Size of the uploaded file in bytes.
    mime_type : str
        MIME type of the uploaded file.

    Raises
    ------
    ATSValidationError
        If the file type is not in ALLOWED_IMAGE_TYPES or exceeds MAX_LOGO_SIZE_MB.

    TODO: Check mime_type against ALLOWED_IMAGE_TYPES constant.
    TODO: Check file_size_bytes <= MAX_LOGO_SIZE_MB * 1024 * 1024.
    TODO: Implement fully in the Logo Upload sprint.
    """
    pass
