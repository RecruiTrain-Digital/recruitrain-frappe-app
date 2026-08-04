# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.offer_validator
=================================================

Input Validation for Offer DocType Payloads.

Validates create, update, and status change payloads for Offer records before
they are processed by ``OfferService``.

All validation functions raise ``ATSValidationError`` on failure.
"""

from __future__ import annotations

import datetime
from typing import Any

import frappe

from recruitrain_employer.utils.constants import (
    DOCTYPE_CANDIDATE,
    DOCTYPE_COMPANY,
    DOCTYPE_INTERVIEW,
    DOCTYPE_JOB_APPLICATION,
    DOCTYPE_JOB_OPENING,
    DOCTYPE_EMPLOYMENT_TYPE,
)
from recruitrain_employer.utils.exceptions import ATSValidationError


ALLOWED_OFFER_STATUSES: list[str] = [
    "Draft",
    "Sent",
    "Accepted",
    "Rejected",
    "Withdrawn",
    "Expired",
]

OFFER_CREATABLE_FIELDS: frozenset[str] = frozenset(
    [
        "offer_name",
        "interview",
        "candidate",
        "job_application",
        "job_opening",
        "company",
        "offered_salary",
        "salary",
        "currency",
        "joining_date",
        "start_date",
        "probation_period_months",
        "offer_date",
        "expiry_date",
        "employment_type",
        "reporting_manager",
        "offer_status",
        "status",
        "response_date",
        "candidate_remarks",
        "notes",
    ]
)

OFFER_UPDATABLE_FIELDS: frozenset[str] = frozenset(
    [
        "offered_salary",
        "salary",
        "currency",
        "joining_date",
        "start_date",
        "probation_period_months",
        "offer_date",
        "expiry_date",
        "employment_type",
        "reporting_manager",
        "offer_status",
        "status",
        "response_date",
        "candidate_remarks",
        "notes",
    ]
)


class OfferValidator:
    """Stateless validator for Offer create, update, and status payloads."""

    def validate_create(self, data: dict) -> None:
        """Validate an Offer create payload."""
        if not data:
            raise ATSValidationError(
                "Payload data is required for offer creation."
            )

        if not data.get("interview") and not data.get("job_application"):
            raise ATSValidationError(
                "Either 'interview' or 'job_application' is required to create an offer.",
                field="interview",
            )

        if data.get("interview"):
            self.validate_interview(data["interview"])

        if data.get("job_application"):
            self.validate_job_application(data["job_application"])

        if data.get("candidate"):
            self.validate_candidate(data["candidate"])

        if data.get("company"):
            self.validate_company(data["company"])

        if data.get("job_opening"):
            self.validate_job_opening(data["job_opening"])

        if data.get("employment_type"):
            self.validate_employment_type(data["employment_type"])

        salary = data.get("offered_salary") or data.get("salary")
        if salary is not None:
            self.validate_salary(salary)

        if data.get("offer_date"):
            self.validate_offer_date(data["offer_date"])

        joining = data.get("joining_date") or data.get("start_date")
        if joining:
            self.validate_joining_date(joining)

        status_val = data.get("offer_status") or data.get("status")
        if status_val:
            self.validate_status(status_val)

    def validate_update(self, data: dict) -> None:
        """Validate an Offer update payload."""
        if not data:
            raise ATSValidationError(
                "No update fields were provided. Please supply at least one field to update."
            )

        disallowed = set(data.keys()) - OFFER_UPDATABLE_FIELDS
        if disallowed:
            raise ATSValidationError(
                f"The following fields cannot be updated: {', '.join(sorted(disallowed))}.",
                details={"disallowed_fields": sorted(disallowed)},
            )

        salary = data.get("offered_salary") or data.get("salary")
        if salary is not None:
            self.validate_salary(salary)

        if data.get("employment_type"):
            self.validate_employment_type(data["employment_type"])

        if data.get("offer_date"):
            self.validate_offer_date(data["offer_date"])

        joining = data.get("joining_date") or data.get("start_date")
        if joining:
            self.validate_joining_date(joining)

        status_val = data.get("offer_status") or data.get("status")
        if status_val:
            self.validate_status(status_val)

    def validate_interview(self, interview_id: str) -> None:
        """Validate that Interview exists."""
        if not interview_id or not frappe.db.exists(DOCTYPE_INTERVIEW, interview_id):
            raise ATSValidationError(
                f"Interview '{interview_id}' does not exist.",
                field="interview",
                details={"interview": interview_id},
            )

    def validate_job_application(self, application_id: str) -> None:
        """Validate that Job Application exists."""
        if not application_id or not frappe.db.exists(DOCTYPE_JOB_APPLICATION, application_id):
            raise ATSValidationError(
                f"Job Application '{application_id}' does not exist.",
                field="job_application",
                details={"job_application": application_id},
            )

    def validate_candidate(self, candidate_id: str) -> None:
        """Validate that Candidate exists."""
        if not candidate_id or not frappe.db.exists(DOCTYPE_CANDIDATE, candidate_id):
            raise ATSValidationError(
                f"Candidate '{candidate_id}' does not exist.",
                field="candidate",
                details={"candidate": candidate_id},
            )

    def validate_company(self, company_id: str) -> None:
        """Validate that Company exists."""
        if not company_id or not frappe.db.exists(DOCTYPE_COMPANY, company_id):
            raise ATSValidationError(
                f"Company '{company_id}' does not exist.",
                field="company",
                details={"company": company_id},
            )

    def validate_job_opening(self, job_opening_id: str) -> None:
        """Validate that Job Opening exists."""
        if not job_opening_id or not frappe.db.exists(DOCTYPE_JOB_OPENING, job_opening_id):
            raise ATSValidationError(
                f"Job Opening '{job_opening_id}' does not exist.",
                field="job_opening",
                details={"job_opening": job_opening_id},
            )

    def validate_employment_type(self, employment_type: str) -> None:
        """Validate employment type exist in master if passed."""
        if employment_type and not frappe.db.exists(DOCTYPE_EMPLOYMENT_TYPE, employment_type):
            raise ATSValidationError(
                f"Employment Type '{employment_type}' does not exist.",
                field="employment_type",
                details={"employment_type": employment_type},
            )

    def validate_salary(self, offered_salary: Any) -> None:
        """Validate that offered_salary is a positive number."""
        try:
            val = float(offered_salary)
            if val <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise ATSValidationError(
                f"Offered salary '{offered_salary}' must be a positive number.",
                field="offered_salary",
            )

    def validate_offer_date(self, value: Any) -> None:
        """Validate offer_date string or date object."""
        self._parse_date(value, field="offer_date")

    def validate_joining_date(self, value: Any) -> None:
        """Validate joining_date string or date object."""
        self._parse_date(value, field="joining_date")

    def validate_status(self, status: str) -> None:
        """Validate that status is in ALLOWED_OFFER_STATUSES."""
        if status not in ALLOWED_OFFER_STATUSES:
            raise ATSValidationError(
                f"'{status}' is not a valid offer status. Allowed values: {', '.join(ALLOWED_OFFER_STATUSES)}.",
                field="offer_status",
                details={"allowed_statuses": ALLOWED_OFFER_STATUSES},
            )

    @staticmethod
    def _parse_date(value: Any, field: str) -> datetime.date:
        """Parse date object or ISO string."""
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
            f"'{value}' is not a valid date format for field '{field}'. Expected format: YYYY-MM-DD.",
            field=field,
        )
