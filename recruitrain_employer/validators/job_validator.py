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
        "profession",
        "employment_type",
        "industry",
        "number_of_openings",
        "number_of_positions",
        "hiring_manager",
        "recruiter",
        "target_joining_date",
        "opening_date",
        "closing_date",
        "minimum_experience",
        "maximum_experience",
        "currency",
        "minimum_salary",
        "maximum_salary",
        "salary_min",
        "salary_max",
        "salary_negotiable",
        "country",
        "state",
        "city",
        "location",
        "remote",
        "hybrid",
        "job_summary",
        "description",
        "responsibilities",
        "requirements",
        "benefits",
        "status",
        "published",
        "featured_job",
    ]
)

#: Fields a caller may modify on an existing Job Opening.
#: ``company`` is excluded — the owning company is immutable after creation.
JOB_UPDATABLE_FIELDS: frozenset[str] = frozenset(
    [
        "job_title",
        "job_code",
        "department",
        "profession",
        "employment_type",
        "industry",
        "number_of_openings",
        "number_of_positions",
        "hiring_manager",
        "recruiter",
        "target_joining_date",
        "opening_date",
        "closing_date",
        "minimum_experience",
        "maximum_experience",
        "currency",
        "minimum_salary",
        "maximum_salary",
        "salary_min",
        "salary_max",
        "salary_negotiable",
        "country",
        "state",
        "city",
        "location",
        "remote",
        "hybrid",
        "job_summary",
        "description",
        "responsibilities",
        "requirements",
        "benefits",
        "status",
        "published",
        "featured_job",
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
        """Validate a Job Opening create payload."""
        self.validate_required_fields(data, JOB_REQUIRED_FIELDS)
        self.validate_salary_range(data)
        self.validate_dates(data)
        self.validate_employment_type(data)
        self.validate_department(data)
        self.validate_company(data)

        if data.get("status"):
            self._validate_status(data["status"])

    def validate_update(self, data: dict) -> None:
        """Validate a Job Opening update payload."""
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
        """Assert that all fields in ``required_fields`` are present and non-empty."""
        missing = []
        for field in required_fields:
            val = data.get(field)
            if field == "job_summary" and not val:
                val = data.get("description")
            elif field == "description" and not val:
                val = data.get("job_summary")
            if not str(val or "").strip():
                missing.append(field)
        if missing:
            raise ATSValidationError(
                f"The following required fields are missing or empty: "
                f"{', '.join(missing)}.",
                details={"missing_fields": missing},
            )

    def validate_salary_range(self, data: dict) -> None:
        """Assert that ``salary_min <= salary_max`` (or minimum_salary <= maximum_salary) when both are provided."""
        salary_min = data.get("minimum_salary") if data.get("minimum_salary") is not None else data.get("salary_min")
        salary_max = data.get("maximum_salary") if data.get("maximum_salary") is not None else data.get("salary_max")

        if salary_min is not None:
            try:
                salary_min = float(salary_min)
            except (TypeError, ValueError):
                raise ATSValidationError(
                    "minimum_salary / salary_min must be a numeric value.",
                    field="minimum_salary",
                )
            if salary_min < 0:
                raise ATSValidationError(
                    "minimum_salary / salary_min cannot be negative.",
                    field="minimum_salary",
                )

        if salary_max is not None:
            try:
                salary_max = float(salary_max)
            except (TypeError, ValueError):
                raise ATSValidationError(
                    "maximum_salary / salary_max must be a numeric value.",
                    field="maximum_salary",
                )
            if salary_max < 0:
                raise ATSValidationError(
                    "maximum_salary / salary_max cannot be negative.",
                    field="maximum_salary",
                )

        if salary_min is not None and salary_max is not None:
            if salary_min > salary_max:
                raise ATSValidationError(
                    f"minimum_salary ({salary_min}) cannot be greater than "
                    f"maximum_salary ({salary_max}).",
                    details={
                        "minimum_salary": salary_min,
                        "maximum_salary": salary_max,
                    },
                )

    def validate_dates(self, data: dict) -> None:
        """Assert that dates are valid if provided."""
        opening_raw = data.get("opening_date")
        closing_raw = data.get("closing_date")
        target_raw = data.get("target_joining_date")

        if target_raw:
            self._parse_date(target_raw, "target_joining_date")

        if opening_raw and closing_raw:
            opening_date = self._parse_date(opening_raw, "opening_date")
            closing_date = self._parse_date(closing_raw, "closing_date")
            if opening_date > closing_date:
                raise ATSValidationError(
                    f"opening_date ({opening_date}) cannot be after closing_date ({closing_date}).",
                    details={"opening_date": str(opening_date), "closing_date": str(closing_date)},
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
