# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.job_application_validator
==========================================================

Input Validation for Job Application DocType Payloads.

Design Principles
-----------------
- All validation methods raise ``ATSValidationError`` on failure.
- Lightweight ``frappe.db.exists`` calls are acceptable for link-existence
  checks (Candidate, Job Opening); no other database reads are performed.
- The validator is fully independent of the API layer and is testable in
  isolation.
- Methods are intentionally small and composable: ``validate_create`` and
  ``validate_update`` delegate to the atomic helpers below.

Allowed Statuses
----------------
``ALLOWED_APPLICATION_STATUSES`` is the canonical allowlist for this sprint.
It maps to the business statuses specified in the Job Application Management
Foundation sprint.  Status validation rejects any value not in this list.

Note on APPLICATION_STAGES (constants.py)
-----------------------------------------
The existing ``APPLICATION_STAGES`` constant in ``constants.py`` uses an
earlier stage vocabulary (``Interview``, ``Assessment``, ``Offer``).  This
validator uses ``ALLOWED_APPLICATION_STATUSES`` — defined here — which matches
the sprint specification:

    Applied → Screening → Shortlisted → Interview Scheduled → Interviewed
    → Offer Extended → Hired → Rejected / Withdrawn

No workflow transition enforcement is implemented in this sprint.  Status
validation only checks membership in the allowed list.

Allowlisted Fields
------------------
``APPLICATION_UPDATABLE_FIELDS`` defines which fields a caller may mutate
through the update endpoint.  ``candidate`` and ``job_opening`` are
intentionally excluded — these are the identity of the application and cannot
change after creation.

Scope — Sprint: Job Application Management Foundation
------------------------------------------------------
Out of scope (implemented in future sprints):

- Forward-only transition rule enforcement
- Terminal-stage blocking (Rejected/Withdrawn → no further transitions)
- Bulk operation validation
- Permissions / company-scoped access control
"""

from __future__ import annotations

import datetime
from typing import Any

import frappe

from recruitrain_employer.utils.constants import (
    APPLICATION_REQUIRED_FIELDS,
    DOCTYPE_CANDIDATE,
    DOCTYPE_JOB_OPENING,
)
from recruitrain_employer.utils.exceptions import ATSValidationError


# ---------------------------------------------------------------------------
# Application Status Allowlist
# ---------------------------------------------------------------------------

#: Canonical list of allowed Job Application statuses for this sprint.
#: Status validation rejects any value not in this list.
#: No transition rules are enforced yet — that is the Application Lifecycle sprint.
ALLOWED_APPLICATION_STATUSES: list[str] = [
    "Applied",
    "Screening",
    "Shortlisted",
    "Interview Scheduled",
    "Interviewed",
    "Offer Extended",
    "Hired",
    "Rejected",
    "Withdrawn",
]

# ---------------------------------------------------------------------------
# Field Allowlists
# ---------------------------------------------------------------------------

#: Fields a caller may supply when creating a new Job Application.
APPLICATION_CREATABLE_FIELDS: frozenset[str] = frozenset(
    [
        "job_opening",
        "candidate",
        "cover_letter",
        "resume",
        "application_date",
        "applied_on",
        "status",
        "current_stage",
        "notes",
        "rejection_reason",
        "source",
        "rating",
        "priority",
        "assigned_recruiter",
    ]
)

#: Fields a caller may modify on an existing Job Application.
#: ``candidate`` and ``job_opening`` are excluded — they are the identity of
#: the application and are immutable after creation.
APPLICATION_UPDATABLE_FIELDS: frozenset[str] = frozenset(
    [
        "cover_letter",
        "resume",
        "application_date",
        "applied_on",
        "status",
        "current_stage",
        "notes",
        "rejection_reason",
        "source",
        "rating",
        "priority",
        "assigned_recruiter",
    ]
)


class JobApplicationValidator:
    """Stateless validator for Job Application create and update payloads.

    Instantiated once per service call.  All methods are side-effect-free
    except for raising ``ATSValidationError`` on invalid input.

    Usage
    -----
    ::

        validator = JobApplicationValidator()
        validator.validate_create(data)   # raises on failure
        validator.validate_update(data)   # raises on failure
    """

    # ------------------------------------------------------------------
    # Top-Level Validators (called by JobApplicationService)
    # ------------------------------------------------------------------

    def validate_create(self, data: dict) -> None:
        """Validate a Job Application create payload.

        Parameters
        ----------
        data : dict
            Raw input data from the API request.

        Raises
        ------
        ATSValidationError
            If any required field is missing, empty, or references a
            non-existent record.

        Checks Performed (in order)
        ---------------------------
        1. All ``APPLICATION_REQUIRED_FIELDS`` (``job_opening``, ``candidate``)
           are present and non-empty.
        2. Referenced ``candidate`` exists in the Candidate master.
        3. Referenced ``job_opening`` exists in the Job Opening master.
        4. ``application_date`` format is valid (if provided).
        5. ``status`` is in ``ALLOWED_APPLICATION_STATUSES`` (if provided).

        Notes
        -----
        Duplicate-application detection is performed separately in
        ``JobApplicationService._assert_unique_application`` so that the
        ``ATSConflictError`` (not ``ATSValidationError``) is raised by the
        service layer rather than the validator.
        """
        self.validate_required_fields(data, list(APPLICATION_REQUIRED_FIELDS))
        self.validate_candidate(data)
        self.validate_job(data)

        if data.get("application_date"):
            self.validate_application_date(data["application_date"])

        if data.get("status"):
            self.validate_status(data["status"])

    def validate_update(self, data: dict) -> None:
        """Validate a Job Application update payload.

        Parameters
        ----------
        data : dict
            Partial Job Application fields from the API request.
            Must be non-empty.

        Raises
        ------
        ATSValidationError
            If ``data`` is empty, contains non-updatable fields, or any
            provided value is invalid.

        Checks Performed (in order)
        ---------------------------
        1. ``data`` contains at least one field (no-op updates are rejected).
        2. All keys in ``data`` are present in ``APPLICATION_UPDATABLE_FIELDS``.
        3. ``application_date`` format is valid (if provided).
        4. ``status`` is in ``ALLOWED_APPLICATION_STATUSES`` (if provided).
        """
        if not data:
            raise ATSValidationError(
                "No update fields were provided. "
                "Please supply at least one field to update."
            )

        disallowed = set(data.keys()) - APPLICATION_UPDATABLE_FIELDS
        if disallowed:
            raise ATSValidationError(
                f"The following fields cannot be updated via this endpoint: "
                f"{', '.join(sorted(disallowed))}.",
                details={"disallowed_fields": sorted(disallowed)},
            )

        if data.get("application_date"):
            self.validate_application_date(data["application_date"])

        if data.get("status"):
            self.validate_status(data["status"])

    # ------------------------------------------------------------------
    # Atomic Validators (reusable across methods)
    # ------------------------------------------------------------------

    def validate_required_fields(
        self, data: dict, required_fields: list[str]
    ) -> None:
        """Assert that all fields in ``required_fields`` are present and non-empty.

        Collects all missing fields before raising so the caller receives a
        complete list in a single error rather than one field at a time.

        Parameters
        ----------
        data : dict
            The input payload to check.
        required_fields : list[str]
            Field names that must be present and have a truthy,
            non-whitespace value.

        Raises
        ------
        ATSValidationError
            Enumerating all missing or empty fields in the ``details`` payload.
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

    def validate_candidate(self, data: dict) -> None:
        """Assert that the ``candidate`` field references an existing Candidate record.

        Skipped when ``candidate`` is absent (required-field check covers that).

        Parameters
        ----------
        data : dict
            The input payload.  Key examined: ``candidate``.

        Raises
        ------
        ATSValidationError
            If the Candidate record does not exist in the database.
        """
        candidate = data.get("candidate")
        if not candidate:
            return

        if not frappe.db.exists(DOCTYPE_CANDIDATE, candidate):
            raise ATSValidationError(
                f"Candidate '{candidate}' does not exist. "
                "Please use a valid Candidate ID.",
                field="candidate",
                details={"candidate": candidate},
            )

    def validate_job(self, data: dict) -> None:
        """Assert that the ``job_opening`` field references an existing Job Opening record.

        Skipped when ``job_opening`` is absent (required-field check covers that).

        Parameters
        ----------
        data : dict
            The input payload.  Key examined: ``job_opening``.

        Raises
        ------
        ATSValidationError
            If the Job Opening record does not exist in the database.
        """
        job_opening = data.get("job_opening")
        if not job_opening:
            return

        if not frappe.db.exists(DOCTYPE_JOB_OPENING, job_opening):
            raise ATSValidationError(
                f"Job Opening '{job_opening}' does not exist. "
                "Please use a valid Job Opening ID.",
                field="job_opening",
                details={"job_opening": job_opening},
            )

    def validate_status(self, status: str) -> None:
        """Assert that ``status`` is in ``ALLOWED_APPLICATION_STATUSES``.

        No workflow transition rules are enforced in this sprint.  Only
        membership in the allowed list is checked.

        Parameters
        ----------
        status : str
            The status value to validate.

        Raises
        ------
        ATSValidationError
            If the status is not a recognised Job Application status.
        """
        if status not in ALLOWED_APPLICATION_STATUSES:
            raise ATSValidationError(
                f"'{status}' is not a valid application status. "
                f"Allowed values: {', '.join(ALLOWED_APPLICATION_STATUSES)}.",
                field="status",
                details={"allowed_statuses": ALLOWED_APPLICATION_STATUSES},
            )

    def validate_application_date(self, value: Any) -> None:
        """Assert that ``application_date`` is a parseable date value.

        Accepts a ``YYYY-MM-DD`` string or a ``datetime.date`` /
        ``datetime.datetime`` object.

        Parameters
        ----------
        value : Any
            The raw ``application_date`` value from the payload.

        Raises
        ------
        ATSValidationError
            If the value cannot be interpreted as a date.
        """
        self._parse_date(value, field="application_date")

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_date(value: Any, field: str) -> datetime.date:
        """Parse ``value`` as a ``datetime.date`` and raise on failure.

        Accepts a ``datetime.date``, ``datetime.datetime``, or a ``str`` in
        ``YYYY-MM-DD`` format.

        Parameters
        ----------
        value : Any
            The raw value to parse.
        field : str
            The field name used in the error message.

        Returns
        -------
        datetime.date
            The parsed date object.

        Raises
        ------
        ATSValidationError
            If the value cannot be interpreted as a date.
        """
        if isinstance(value, datetime.datetime):
            return value.date()

        if isinstance(value, datetime.date):
            return value

        if isinstance(value, str):
            try:
                return datetime.date.fromisoformat(value.strip())
            except ValueError:
                pass

        raise ATSValidationError(
            f"'{value}' is not a valid date for field '{field}'. "
            "Expected format: YYYY-MM-DD.",
            field=field,
        )
