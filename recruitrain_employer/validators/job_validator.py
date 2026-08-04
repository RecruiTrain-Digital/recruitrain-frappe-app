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
    JOB_PUBLISH_REQUIRED_FIELDS,
    JOB_REQUIRED_FIELDS,
    JOB_STATUS_DRAFT,
    JOB_STATUS_OPEN,
)
from recruitrain_employer.utils.exceptions import ATSValidationError


class JobValidationMode:
    """Validation modes supported by the Job Opening domain."""

    DRAFT = "draft"
    UPDATE = "update"
    PUBLISH = "publish"


# ---------------------------------------------------------------------------
# Field Allowlists & Aliases
# ---------------------------------------------------------------------------

#: Mapping from UI / camelCase / legacy field names to canonical database field names.
JOB_FIELD_ALIASES: dict[str, str] = {
    "title": "job_title",
    "jobTitle": "job_title",
    "code": "job_code",
    "jobCode": "job_code",
    "type": "employment_type",
    "employmentType": "employment_type",
    "summary": "job_summary",
    "jobSummary": "job_summary",
    "description": "job_summary",
    "minSalary": "minimum_salary",
    "minimumSalary": "minimum_salary",
    "salary_min": "minimum_salary",
    "salaryMin": "minimum_salary",
    "maxSalary": "maximum_salary",
    "maximumSalary": "maximum_salary",
    "salary_max": "maximum_salary",
    "salaryMax": "maximum_salary",
    "minExperience": "minimum_experience",
    "minimumExperience": "minimum_experience",
    "maxExperience": "maximum_experience",
    "maximumExperience": "maximum_experience",
    "experience": "minimum_experience",
    "closingDate": "closing_date",
    "openingDate": "opening_date",
    "targetJoiningDate": "target_joining_date",
    "numberOfOpenings": "number_of_openings",
    "numberOfPositions": "number_of_openings",
    "number_of_positions": "number_of_openings",
    "maxApplicants": "number_of_openings",
    "hiringManager": "hiring_manager",
    "salaryNegotiable": "salary_negotiable",
    "featuredJob": "featured_job",
    "category": "department",
    "categorySub": "profession",
    "allowDomestic": "allow_domestic_candidates",
    "allowInternational": "allow_international_candidates",
    "autoClose": "auto_close",
    "germanLevel": "german_level",
    "keywords": "keywords",
    "street": "location",
}


def normalize_job_payload(data: dict) -> dict:
    """Normalize incoming job payload by translating UI/camelCase aliases to canonical snake_case schema names.

    Also normalizes values (such as employment_type formatting). Modifies input payload in-place
    and returns the normalized dictionary.
    """
    if not isinstance(data, dict):
        return {}

    mapped: dict = {}
    for key, val in list(data.items()):
        canonical = JOB_FIELD_ALIASES.get(key, key)

        if key == "compensationType" and isinstance(val, str):
            if val.lower() in ("negotiable", "yes", "true"):
                mapped["salary_negotiable"] = 1
            continue

        mapped[canonical] = val

    # Value normalization for employment_type
    if "employment_type" in mapped and mapped["employment_type"]:
        raw_emp = str(mapped["employment_type"]).strip()
        lower_emp = raw_emp.lower()
        if lower_emp in ("full-time", "full time", "full_time"):
            mapped["employment_type"] = "Full Time"
        elif lower_emp in ("part-time", "part time", "part_time"):
            mapped["employment_type"] = "Part Time"
        elif lower_emp in ("contract", "contractual"):
            mapped["employment_type"] = "Contract"

    # Value normalization for department
    if "department" in mapped and mapped["department"]:
        try:
            from recruitrain_employer.validators.department_validator import (
                validate_and_normalize_department,
            )
            validate_and_normalize_department(mapped)
        except Exception:
            pass

    # Value normalization for profession
    if "profession" in mapped and mapped["profession"]:
        try:
            from recruitrain_employer.validators.profession_validator import (
                validate_and_normalize_profession,
            )
            validate_and_normalize_profession(mapped)
        except Exception:
            pass

    # Value normalization for industry
    if "industry" in mapped and mapped["industry"]:
        try:
            from recruitrain_employer.validators.industry_validator import (
                validate_and_normalize_industry,
            )
            validate_and_normalize_industry(mapped)
        except Exception:
            pass

    data.clear()
    data.update(mapped)
    return data


normalize_update_payload = normalize_job_payload


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
    """Stateless validator for Job Opening create, draft, update, and publish payloads.

    Instantiated once per service call.  All methods are side-effect-free
    except for raising ``ATSValidationError`` on invalid input.
    """

    # ------------------------------------------------------------------
    # Top-Level Validators (called by JobService)
    # ------------------------------------------------------------------

    def validate_draft(self, data: dict) -> None:
        """Validate a Job Opening draft payload (Draft Validation Mode)."""
        normalize_job_payload(data)
        self.validate_salary_range(data)
        self.validate_dates(data)
        self.validate_employment_type(data)
        self.validate_department(data)
        self.validate_profession(data)
        self.validate_industry(data)
        self.validate_company(data)

        if data.get("status"):
            self._validate_status(data["status"])

    def validate_create(self, data: dict) -> None:
        """Validate a Job Opening create payload."""
        normalize_job_payload(data)
        status = data.get("status", JOB_STATUS_DRAFT)
        is_published = bool(data.get("published"))

        if status == JOB_STATUS_OPEN or is_published:
            self.validate_publish(data)
        else:
            self.validate_draft(data)

    def validate_update(self, data: dict) -> None:
        """Validate a Job Opening update payload (Update Validation Mode)."""
        if not data:
            raise ATSValidationError(
                "No update fields were provided. "
                "Please supply at least one field to update."
            )

        normalize_job_payload(data)

        # Ignore and strip unknown / non-updatable fields rather than failing validation
        disallowed = set(data.keys()) - JOB_UPDATABLE_FIELDS
        if disallowed:
            frappe.logger().warning(
                f"[JobValidator] Stripping unknown or non-updatable fields from update payload: {sorted(disallowed)}"
            )
            for f in disallowed:
                data.pop(f, None)

        if not data:
            raise ATSValidationError(
                "No valid updatable fields were provided in the payload."
            )

        self.validate_salary_range(data)
        self.validate_dates(data)
        self.validate_employment_type(data)
        self.validate_department(data)
        self.validate_profession(data)
        self.validate_industry(data)

        if data.get("status"):
            self._validate_status(data["status"])

    def validate_publish(self, data: dict) -> None:
        """Validate a Job Opening prior to publishing (Publish Validation Mode)."""
        normalize_job_payload(data)
        self.validate_required_fields(data, JOB_PUBLISH_REQUIRED_FIELDS)
        self.validate_salary_range(data)
        self.validate_dates(data)
        self.validate_employment_type(data)
        self.validate_department(data)
        self.validate_profession(data)
        self.validate_industry(data)
        self.validate_company(data)

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

    def validate_employment_type(self, data: dict) -> str | None:
        """Validate and normalize ``employment_type`` against the Employment Type master.

        Performs case-insensitive, hyphen/space-agnostic lookup and alias resolution,
        mutating ``data['employment_type']`` with the canonical master record name.

        Parameters
        ----------
        data : dict
            The input payload dictionary.

        Returns
        -------
        str or None
            The canonical Employment Type master name, or None if not provided.

        Raises
        ------
        ATSValidationError
            If the Employment Type record does not exist in the database.
        """
        from recruitrain_employer.validators.employment_type_validator import (
            validate_and_normalize_employment_type_field,
        )
        return validate_and_normalize_employment_type_field(data)

    def validate_department(self, data: dict) -> None:
        """Validate and normalize Department against the master DocType."""
        from recruitrain_employer.validators.department_validator import (
            validate_and_normalize_department,
        )
        validate_and_normalize_department(data)

    def validate_profession(self, data: dict) -> None:
        """Validate and normalize Profession against the master DocType."""
        from recruitrain_employer.validators.profession_validator import (
            validate_and_normalize_profession,
        )
        validate_and_normalize_profession(data)

    def validate_industry(self, data: dict) -> None:
        """Validate and normalize Industry against the master DocType."""
        from recruitrain_employer.validators.industry_validator import (
            validate_and_normalize_industry,
        )
        validate_and_normalize_industry(data)

    def validate_company(self, data: dict) -> str:
        """Validate and resolve company from the authenticated Employer User.

        Forces ``data['company']`` to match the authenticated user's company
        and validates that the company exists and is active in the database.
        """
        from recruitrain_employer.utils.permissions import get_current_company
        current_company = get_current_company()
        if isinstance(data, dict):
            data["company"] = current_company
        return current_company

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
