# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.job_validator
===============================================

Input Validation & Payload Normalization for Job Opening DocType Payloads.

Design Principles
-----------------
- All validation methods raise ``ATSValidationError`` on failure.
- Resolvers handle fuzzy/case-insensitive/hyphen-insensitive master resolution.
- Three distinct validation modes are implemented:
  1. ``validate_draft()``: Permissive, minimal validation for autosave & drafts.
  2. ``validate_update()``: Validates only supplied/modified fields.
  3. ``validate_publish()``: Strict production validation for publishing live jobs.
- Payload normalization converts UI/camelCase/legacy aliases into canonical backend snake_case.
- Company resolution is strictly scoped to `get_current_company()`.
"""

from __future__ import annotations

import datetime
from typing import Any

import frappe

from recruitrain_employer.utils.constants import (
    ALLOWED_JOB_STATUSES,
    JOB_PUBLISH_REQUIRED_FIELDS,
    JOB_STATUS_DRAFT,
    JOB_STATUS_OPEN,
)
from recruitrain_employer.utils.exceptions import ATSValidationError
from recruitrain_employer.validators.department_validator import DepartmentResolver
from recruitrain_employer.validators.employment_type_validator import EmploymentTypeResolver
from recruitrain_employer.validators.profession_validator import ProfessionResolver


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

    Also resolves master Link fields (Department, Profession, Employment Type) using robust resolvers.
    Modifies input payload in-place and returns the normalized dictionary.
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
    if mapped.get("employment_type"):
        try:
            mapped["employment_type"] = EmploymentTypeResolver.resolve(str(mapped["employment_type"]))
        except Exception:
            pass

    # Value normalization for department
    if mapped.get("department"):
        try:
            mapped["department"] = DepartmentResolver.resolve(str(mapped["department"]))
        except Exception:
            pass

    # Value normalization for profession
    if mapped.get("profession"):
        try:
            mapped["profession"] = ProfessionResolver.resolve(str(mapped["profession"]))
        except Exception:
            pass

    # Value normalization for industry
    if mapped.get("industry"):
        try:
            from recruitrain_employer.validators.industry_validator import validate_and_normalize_industry
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
        "published_at",
        "published_by",
        "featured_job",
    ]
)

#: Fields a caller may modify on an existing Job Opening.
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
        "published_at",
        "published_by",
        "featured_job",
    ]
)


class JobValidator:
    """Stateless validator for Job Opening create, draft, update, and publish payloads."""

    def validate_draft(self, data: dict) -> None:
        """Validate a Job Opening draft payload (Draft Validation Mode).

        Permissive mode — only validates numerical logic, dates, and resolves link fields if supplied.
        Does NOT require mandatory publish fields.
        """
        normalize_job_payload(data)
        self.validate_salary_range(data)
        self.validate_dates(data)
        self.validate_employment_type(data)
        self.validate_department(data)
        self.validate_profession(data)
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
                "No update fields were provided. Please supply at least one field to update."
            )

        normalize_job_payload(data)

        disallowed = set(data.keys()) - JOB_UPDATABLE_FIELDS
        if disallowed:
            frappe.logger().warning(
                f"[JobValidator] Stripping unknown or non-updatable fields from update payload: {sorted(disallowed)}"
            )
            for f in disallowed:
                data.pop(f, None)

        if not data:
            raise ATSValidationError("No valid updatable fields were provided in the payload.")

        self.validate_salary_range(data)
        self.validate_dates(data)
        self.validate_employment_type(data)
        self.validate_department(data)
        self.validate_profession(data)

        if data.get("status"):
            self._validate_status(data["status"])

    def validate_publish(self, data: dict) -> None:
        """Validate a Job Opening prior to publishing (Publish Validation Mode)."""
        normalize_job_payload(data)
        self.validate_company(data)
        self.validate_required_fields(data, JOB_PUBLISH_REQUIRED_FIELDS)
        self.validate_salary_range(data)
        self.validate_dates(data)
        self.validate_employment_type(data, strict=True)
        self.validate_department(data, strict=True)
        self.validate_profession(data, strict=True)

        if data.get("status"):
            self._validate_status(data["status"])

    def validate_required_fields(self, data: dict, required_fields: list[str]) -> None:
        """Assert that all fields in ``required_fields`` are present and non-empty."""
        missing = []
        for field in required_fields:
            if field == "company":
                continue
            val = data.get(field)
            if field == "job_summary" and not val:
                val = data.get("description")
            elif field == "description" and not val:
                val = data.get("job_summary")
            if not str(val or "").strip():
                missing.append(field)
        if missing:
            raise ATSValidationError(
                f"The following required fields are missing or empty: {', '.join(missing)}.",
                details={"missing_fields": missing},
            )

    def validate_salary_range(self, data: dict) -> None:
        """Assert that ``salary_min <= salary_max`` when both are provided."""
        salary_min = data.get("minimum_salary") if data.get("minimum_salary") is not None else data.get("salary_min")
        salary_max = data.get("maximum_salary") if data.get("maximum_salary") is not None else data.get("salary_max")

        if salary_min is not None and str(salary_min).strip() != "":
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
        else:
            salary_min = None

        if salary_max is not None and str(salary_max).strip() != "":
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
        else:
            salary_max = None

        if salary_min is not None and salary_max is not None:
            if salary_min > salary_max:
                raise ATSValidationError(
                    f"minimum_salary ({salary_min}) cannot be greater than maximum_salary ({salary_max}).",
                    details={"minimum_salary": salary_min, "maximum_salary": salary_max},
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

    def validate_employment_type(self, data: dict, strict: bool = False) -> str | None:
        """Validate and resolve Employment Type using EmploymentTypeResolver."""
        raw_val = data.get("employment_type")
        if not raw_val:
            if strict:
                raise ATSValidationError("Employment Type is required for publishing.", field="employment_type")
            return None
        canonical = EmploymentTypeResolver.resolve(str(raw_val))
        data["employment_type"] = canonical
        return canonical

    def validate_department(self, data: dict, strict: bool = False) -> str | None:
        """Validate and resolve Department using DepartmentResolver."""
        raw_val = data.get("department")
        if not raw_val:
            if strict:
                pass  # Department is optional in Job Opening, but if present must be resolved
            return None
        canonical = DepartmentResolver.resolve(str(raw_val))
        data["department"] = canonical
        return canonical

    def validate_profession(self, data: dict, strict: bool = False) -> str | None:
        """Validate and resolve Profession using ProfessionResolver, ensuring it belongs to data['department']."""
        raw_val = data.get("profession")
        if not raw_val:
            return None
        dept_val = data.get("department")
        canonical = ProfessionResolver.resolve(str(raw_val), department=str(dept_val) if dept_val else None)
        data["profession"] = canonical
        return canonical

    def validate_company(self, data: dict) -> str:
        """Validate and resolve company strictly from the authenticated Employer User.

        Never trusts input company in payload.
        """
        from recruitrain_employer.utils.permissions import get_current_company
        current_company = get_current_company()
        if isinstance(data, dict):
            data["company"] = current_company
        return current_company

    @staticmethod
    def _parse_date(value: Any, field: str) -> datetime.date:
        """Parse value as a datetime.date."""
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
            f"'{value}' is not a valid date for field '{field}'. Expected format: YYYY-MM-DD.",
            field=field,
        )

    @staticmethod
    def _validate_status(status: str) -> None:
        """Assert status is in ALLOWED_JOB_STATUSES."""
        if status not in ALLOWED_JOB_STATUSES:
            raise ATSValidationError(
                f"'{status}' is not a valid Job Opening status. Allowed values: {', '.join(ALLOWED_JOB_STATUSES)}.",
                field="status",
                details={"allowed_statuses": ALLOWED_JOB_STATUSES},
            )
