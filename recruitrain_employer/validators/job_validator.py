# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.job_validator
===============================================

Input Validation for Job Opening DocType Payloads.

Design Principles
-----------------
- All validation methods raise ``ATSValidationError`` on failure.
- Lightweight ``frappe.db.exists`` calls are acceptable for link-existence
  checks; no other database reads are performed here.
- The validator is fully independent of the API layer and can be unit-tested
  in isolation.
- Methods are intentionally small and composable: ``validate_create`` and
  ``validate_update`` delegate to the atomic helpers below.

Allowlisted Fields
------------------
``JOB_UPDATABLE_FIELDS`` defines which fields a caller may mutate through the
update endpoint.  ``company`` is intentionally excluded from updates — the
company that owns a Job Opening cannot be changed after creation.  System
fields (``name``, ``owner``, ``creation``, ``modified``, ``docstatus``) are
never in this list.

Salary Validation
-----------------
``validate_salary_range`` enforces that ``salary_min <= salary_max`` when both
are provided.  Neither field is individually required; the constraint only
applies when both are present.  Negative values are also rejected.

Date Validation
---------------
``validate_dates`` enforces that ``opening_date <= closing_date`` when both
are provided.  Dates are accepted as strings (``YYYY-MM-DD``) or ``datetime``
objects; comparison is done after coercing to ``datetime.date``.

Linked-Record Validation
------------------------
``validate_company`` and ``validate_department`` perform lightweight
``frappe.db.exists`` checks.  Department validation is only performed when a
``department`` value is supplied (it is optional on Job Openings).

Scope — Sprint: Job Opening Management Foundation
--------------------------------------------------
Out of scope (implemented in future sprints):

- Publishing / closing workflow validation (``validate_publish``)
- Approval workflow
- Notifications
- Permissions
"""

from __future__ import annotations

import datetime
from typing import Any

import frappe

from recruitrain_employer.utils.constants import (
    ALLOWED_JOB_STATUSES,
    DOCTYPE_COMPANY,
    DOCTYPE_DEPARTMENT,
    DOCTYPE_EMPLOYMENT_TYPE,
    JOB_REQUIRED_FIELDS,
)
from recruitrain_employer.utils.exceptions import ATSValidationError


# ---------------------------------------------------------------------------
# Field Allowlists
# ---------------------------------------------------------------------------

#: Fields a caller may supply when creating a new Job Opening.
JOB_CREATABLE_FIELDS: frozenset[str] = frozenset(
    [
        "job_title",
        "job_code",
        "company",
        "department",
        "employment_type",
        "location",
        "description",
        "job_summary",
        "responsibilities",
        "requirements",
        "benefits",
        "salary_min",
        "salary_max",
        "minimum_salary",
        "maximum_salary",
        "currency",
        "status",
        "opening_date",
        "closing_date",
        "target_joining_date",
        "number_of_positions",
        "number_of_openings",
        "country",
        "state",
        "city",
        "remote",
        "hybrid",
    ]
)

#: Fields a caller may modify on an existing Job Opening.
#: ``company`` is excluded — the owning company is immutable after creation.
JOB_UPDATABLE_FIELDS: frozenset[str] = frozenset(
    [
        "job_title",
        "job_code",
        "department",
        "employment_type",
        "location",
        "description",
        "job_summary",
        "responsibilities",
        "requirements",
        "benefits",
        "salary_min",
        "salary_max",
        "minimum_salary",
        "maximum_salary",
        "currency",
        "status",
        "opening_date",
        "closing_date",
        "target_joining_date",
        "number_of_positions",
        "number_of_openings",
        "country",
        "state",
        "city",
        "remote",
        "hybrid",
    ]
)


class JobValidator:
    """Stateless validator for Job Opening create and update payloads.

    Instantiated once per service call.  All methods are side-effect-free
    except for raising ``ATSValidationError`` on invalid input.

    Usage
    -----
    ::

        validator = JobValidator()
        validator.validate_create(data)   # raises on failure
        validator.validate_update(data)   # raises on failure
    """

    # ------------------------------------------------------------------
    # Top-Level Validators (called by JobService)
    # ------------------------------------------------------------------

    def validate_create(self, data: dict) -> None:
        """Validate a Job Opening create payload.

        Parameters
        ----------
        data : dict
            Raw input data from the API request.

        Raises
        ------
        ATSValidationError
            If any required field is missing, empty, or has an invalid value.

        Checks Performed (in order)
        ---------------------------
        1. All ``JOB_REQUIRED_FIELDS`` are present and non-empty.
        2. Salary range is valid: ``salary_min <= salary_max`` (if both provided).
        3. Opening/closing date constraint: ``opening_date <= closing_date`` (if both provided).
        4. ``employment_type`` exists in the Employment Type master (if provided).
        5. ``department`` exists in the Department master (if provided).
        6. ``company`` exists in the Company master.
        7. ``status`` is in ``ALLOWED_JOB_STATUSES`` (if provided).
        """
        self.validate_required_fields(data, JOB_REQUIRED_FIELDS)
        self.validate_salary_range(data)
        self.validate_dates(data)
        self.validate_employment_type(data)
        self.validate_department(data)
        self.validate_company(data)

        if data.get("status"):
            self._validate_status(data["status"])

    def validate_update(self, data: dict) -> None:
        """Validate a Job Opening update payload.

        Parameters
        ----------
        data : dict
            Partial Job Opening fields from the API request.  Must be non-empty.

        Raises
        ------
        ATSValidationError
            If ``data`` is empty, contains non-updatable fields, or any
            provided value is invalid.

        Checks Performed (in order)
        ---------------------------
        1. ``data`` contains at least one field (no-op updates are rejected).
        2. All keys in ``data`` are present in ``JOB_UPDATABLE_FIELDS``.
        3. Salary range is valid (if both min and max are present after merge).
        4. Date constraint is valid (if both dates are present).
        5. ``employment_type`` exists (if provided).
        6. ``department`` exists (if provided).
        7. ``status`` is in ``ALLOWED_JOB_STATUSES`` (if provided).
        """
        if not data:
            raise ATSValidationError(
                "No update fields were provided. "
                "Please supply at least one field to update."
            )

        disallowed = set(data.keys()) - JOB_UPDATABLE_FIELDS
        if disallowed:
            raise ATSValidationError(
                f"The following fields cannot be updated via this endpoint: "
                f"{', '.join(sorted(disallowed))}.",
                details={"disallowed_fields": sorted(disallowed)},
            )

        self.validate_salary_range(data)
        self.validate_dates(data)
        self.validate_employment_type(data)
        self.validate_department(data)

        if data.get("status"):
            self._validate_status(data["status"])

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
            Field names that must be present and have a truthy, non-whitespace value.

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

    def validate_salary_range(self, data: dict) -> None:
        """Assert that ``salary_min <= salary_max`` when both are provided.

        Neither field is individually required.  The constraint only applies
        when both values are present in ``data``.  Negative values are
        rejected unconditionally.

        Parameters
        ----------
        data : dict
            The input payload.  Keys examined: ``salary_min``, ``salary_max``.

        Raises
        ------
        ATSValidationError
            If either salary is negative, or if ``salary_min > salary_max``.
        """
        salary_min = data.get("salary_min")
        salary_max = data.get("salary_max")

        if salary_min is not None:
            try:
                salary_min = float(salary_min)
            except (TypeError, ValueError):
                raise ATSValidationError(
                    "salary_min must be a numeric value.",
                    field="salary_min",
                )
            if salary_min < 0:
                raise ATSValidationError(
                    "salary_min cannot be negative.",
                    field="salary_min",
                )

        if salary_max is not None:
            try:
                salary_max = float(salary_max)
            except (TypeError, ValueError):
                raise ATSValidationError(
                    "salary_max must be a numeric value.",
                    field="salary_max",
                )
            if salary_max < 0:
                raise ATSValidationError(
                    "salary_max cannot be negative.",
                    field="salary_max",
                )

        if salary_min is not None and salary_max is not None:
            if salary_min > salary_max:
                raise ATSValidationError(
                    f"salary_min ({salary_min}) cannot be greater than "
                    f"salary_max ({salary_max}).",
                    details={
                        "salary_min": salary_min,
                        "salary_max": salary_max,
                    },
                )

    def validate_dates(self, data: dict) -> None:
        """Assert that ``opening_date <= closing_date`` when both are provided.

        Accepts dates as ``YYYY-MM-DD`` strings or ``datetime.date`` objects.
        Neither field is individually required; the constraint only applies
        when both are present.

        Parameters
        ----------
        data : dict
            The input payload.  Keys examined: ``opening_date``, ``closing_date``.

        Raises
        ------
        ATSValidationError
            If either date has an unrecognisable format, or if
            ``opening_date > closing_date``.
        """
        opening_raw = data.get("opening_date")
        closing_raw = data.get("closing_date")

        if not opening_raw and not closing_raw:
            return

        opening_date = self._parse_date(opening_raw, "opening_date") if opening_raw else None
        closing_date = self._parse_date(closing_raw, "closing_date") if closing_raw else None

        if opening_date and closing_date and opening_date > closing_date:
            raise ATSValidationError(
                f"opening_date ({opening_date}) cannot be after "
                f"closing_date ({closing_date}).",
                details={
                    "opening_date": str(opening_date),
                    "closing_date": str(closing_date),
                },
            )

    def validate_employment_type(self, data: dict) -> None:
        """Assert that ``employment_type`` exists in the Employment Type master.

        Validation is skipped when ``employment_type`` is not provided.

        Parameters
        ----------
        data : dict
            The input payload.  Key examined: ``employment_type``.

        Raises
        ------
        ATSValidationError
            If the Employment Type record does not exist in the database.
        """
        employment_type = data.get("employment_type")
        if not employment_type:
            return

        if not frappe.db.exists(DOCTYPE_EMPLOYMENT_TYPE, employment_type):
            raise ATSValidationError(
                f"Employment Type '{employment_type}' does not exist. "
                "Please use a valid Employment Type from the master list.",
                field="employment_type",
                details={"employment_type": employment_type},
            )

    def validate_department(self, data: dict) -> None:
        """Assert that ``department`` exists in the Department master when provided.

        Department is optional on a Job Opening.  Validation is skipped when
        the field is absent or empty.

        Parameters
        ----------
        data : dict
            The input payload.  Key examined: ``department``.

        Raises
        ------
        ATSValidationError
            If the Department record does not exist in the database.
        """
        department = data.get("department")
        if not department:
            return

        if not frappe.db.exists(DOCTYPE_DEPARTMENT, department):
            raise ATSValidationError(
                f"Department '{department}' does not exist. "
                "Please use a valid Department from the master list.",
                field="department",
                details={"department": department},
            )

    def validate_company(self, data: dict) -> None:
        """Assert that the ``company`` field references an existing Company record.

        This check is performed only during creation (``validate_create``);
        ``company`` is excluded from the updatable-fields allowlist so this
        validator is never called on updates.

        Parameters
        ----------
        data : dict
            The input payload.  Key examined: ``company``.

        Raises
        ------
        ATSValidationError
            If the Company record does not exist in the database.
        """
        company = data.get("company")
        if not company:
            # Required-field check in validate_required_fields already covers
            # the missing-company case; skip here to avoid duplicate errors.
            return

        if not frappe.db.exists(DOCTYPE_COMPANY, company):
            raise ATSValidationError(
                f"Company '{company}' does not exist. "
                "Please use a valid Company name.",
                field="company",
                details={"company": company},
            )

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

    @staticmethod
    def _validate_status(status: str) -> None:
        """Assert that ``status`` is in ``ALLOWED_JOB_STATUSES``.

        Parameters
        ----------
        status : str
            The status value to validate.

        Raises
        ------
        ATSValidationError
            If the status is not a recognised Job Opening status.
        """
        if status not in ALLOWED_JOB_STATUSES:
            raise ATSValidationError(
                f"'{status}' is not a valid Job Opening status. "
                f"Allowed values: {', '.join(ALLOWED_JOB_STATUSES)}.",
                field="status",
                details={"allowed_statuses": ALLOWED_JOB_STATUSES},
            )
