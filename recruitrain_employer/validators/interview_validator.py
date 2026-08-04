# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.interview_validator
=====================================================

Input Validation for Interview DocType Payloads.

Validates create, update, and status change payloads for Interview records
before they are processed by ``InterviewService``.

All validation functions raise ``ATSValidationError`` on failure.
"""

from __future__ import annotations

import datetime
from typing import Any

import frappe

from recruitrain_employer.utils.constants import (
    DOCTYPE_CANDIDATE,
    DOCTYPE_JOB_APPLICATION,
    DOCTYPE_JOB_OPENING,
    DOCTYPE_COMPANY,
)
from recruitrain_employer.utils.exceptions import ATSValidationError


#: Allowed Interview statuses as defined by system specifications:
ALLOWED_INTERVIEW_STATUSES: list[str] = [
    "Scheduled",
    "Rescheduled",
    "Completed",
    "Cancelled",
    "No Show",
]

#: Allowed Interview types supported by Interview DocType:
ALLOWED_INTERVIEW_TYPES: list[str] = [
    "Phone",
    "Video",
    "Technical",
    "HR",
    "Managerial",
    "Final",
    "Phone Screen",
    "Video Call",
    "Panel",
    "Onsite",
]

#: Fields allowed when creating an Interview:
INTERVIEW_CREATABLE_FIELDS: frozenset[str] = frozenset(
    [
        "interview_name",
        "job_application",
        "candidate",
        "job_opening",
        "company",
        "interview_type",
        "scheduled_on",
        "duration",
        "meeting_link",
        "location",
        "interviewer",
        "recruiter",
        "result",
        "status",
        "remarks",
    ]
)

#: Fields allowed when updating an Interview:
INTERVIEW_UPDATABLE_FIELDS: frozenset[str] = frozenset(
    [
        "interview_type",
        "scheduled_on",
        "duration",
        "meeting_link",
        "location",
        "interviewer",
        "recruiter",
        "result",
        "status",
        "remarks",
    ]
)


class InterviewValidator:
    """Stateless validator for Interview create, update, and status payloads."""

    def validate_create(self, data: dict) -> None:
        """Validate an Interview creation payload."""
        if not data:
            raise ATSValidationError(
                "Payload data is required for interview creation."
            )

        # Check required field presence
        if not data.get("job_application"):
            raise ATSValidationError(
                "job_application is required.", field="job_application"
            )

        if not data.get("interview_type"):
            raise ATSValidationError(
                "interview_type is required.", field="interview_type"
            )

        # Entity Link checks
        self.validate_job_application(data.get("job_application"))

        if data.get("candidate"):
            self.validate_candidate(data["candidate"])

        if data.get("job_opening"):
            self.validate_job_opening(data["job_opening"])

        if data.get("company"):
            self.validate_company(data["company"])

        if data.get("interviewer"):
            self.validate_interviewer(data["interviewer"])

        # Type & Datetime validations
        self.validate_interview_type(data["interview_type"])

        if data.get("scheduled_on"):
            self.validate_scheduled_on(data["scheduled_on"])

        if data.get("status"):
            self.validate_status(data["status"])

        if data.get("duration") is not None:
            self.validate_duration(data["duration"])

    def validate_update(self, data: dict) -> None:
        """Validate an Interview update payload."""
        if not data:
            raise ATSValidationError(
                "No update fields were provided. Please supply at least one field to update."
            )

        disallowed = set(data.keys()) - INTERVIEW_UPDATABLE_FIELDS
        if disallowed:
            raise ATSValidationError(
                f"The following fields cannot be updated: {', '.join(sorted(disallowed))}.",
                details={"disallowed_fields": sorted(disallowed)},
            )

        if "interview_type" in data:
            self.validate_interview_type(data["interview_type"])

        if "interviewer" in data and data["interviewer"]:
            self.validate_interviewer(data["interviewer"])

        if "scheduled_on" in data and data["scheduled_on"]:
            self.validate_scheduled_on(data["scheduled_on"])

        if "status" in data and data["status"]:
            self.validate_status(data["status"])

        if "duration" in data and data["duration"] is not None:
            self.validate_duration(data["duration"])

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

    def validate_job_opening(self, job_opening_id: str) -> None:
        """Validate that Job Opening exists."""
        if not job_opening_id or not frappe.db.exists(DOCTYPE_JOB_OPENING, job_opening_id):
            raise ATSValidationError(
                f"Job Opening '{job_opening_id}' does not exist.",
                field="job_opening",
                details={"job_opening": job_opening_id},
            )

    def validate_company(self, company_id: str) -> None:
        """Validate that Company exists."""
        if not company_id or not frappe.db.exists(DOCTYPE_COMPANY, company_id):
            raise ATSValidationError(
                f"Company '{company_id}' does not exist.",
                field="company",
                details={"company": company_id},
            )

    def validate_interviewer(self, interviewer_id: str) -> None:
        """Validate that Interviewer exists in User DocType."""
        if not interviewer_id or not frappe.db.exists("User", interviewer_id):
            raise ATSValidationError(
                f"Interviewer user '{interviewer_id}' does not exist.",
                field="interviewer",
                details={"interviewer": interviewer_id},
            )

    def validate_scheduled_on(self, value: Any) -> None:
        """Validate that scheduled_on is a valid datetime or date."""
        if isinstance(value, (datetime.datetime, datetime.date)):
            return

        if isinstance(value, str):
            value_str = value.strip()
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%d",
            ):
                try:
                    datetime.datetime.strptime(value_str, fmt)
                    return
                except ValueError:
                    continue
            try:
                datetime.datetime.fromisoformat(value_str)
                return
            except ValueError:
                pass

        raise ATSValidationError(
            f"'{value}' is not a valid date/time format for 'scheduled_on'. Expected YYYY-MM-DD HH:MM:SS or ISO format.",
            field="scheduled_on",
        )

    def validate_interview_type(self, interview_type: str) -> None:
        """Validate that interview_type is in allowed interview types."""
        if interview_type not in ALLOWED_INTERVIEW_TYPES:
            raise ATSValidationError(
                f"'{interview_type}' is not a valid interview type. Allowed values: {', '.join(ALLOWED_INTERVIEW_TYPES)}.",
                field="interview_type",
                details={"allowed_types": ALLOWED_INTERVIEW_TYPES},
            )

    def validate_status(self, status: str) -> None:
        """Validate that status is in ALLOWED_INTERVIEW_STATUSES."""
        if status not in ALLOWED_INTERVIEW_STATUSES:
            raise ATSValidationError(
                f"'{status}' is not a valid interview status. Allowed values: {', '.join(ALLOWED_INTERVIEW_STATUSES)}.",
                field="status",
                details={"allowed_statuses": ALLOWED_INTERVIEW_STATUSES},
            )

    def validate_duration(self, duration: Any) -> None:
        """Validate that duration is a positive integer."""
        try:
            val = int(duration)
            if val < 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise ATSValidationError(
                f"Duration '{duration}' must be a non-negative integer (in minutes).",
                field="duration",
            )
