# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.job_validator
===============================================

Input Validation for Job Opening DocType Payloads.

Validates create and update payloads for Job Opening records before they
are processed by ``JobService``.

All validation functions raise ``ATSValidationError`` on failure.
"""

from __future__ import annotations

from recruitrain_employer.utils.constants import (
    JOB_REQUIRED_FIELDS,
    JOB_STATUS_DRAFT,
    JOB_STATUS_OPEN,
    JOB_STATUS_CLOSED,
    ALLOWED_JOB_STATUSES,
)
from recruitrain_employer.utils.exceptions import ATSValidationError


# ---------------------------------------------------------------------------
# Create Validation
# ---------------------------------------------------------------------------


def validate_create(data: dict) -> None:
    """Validate a Job Opening create payload.

    Parameters
    ----------
    data : dict
        Raw input data from the API request.

    Raises
    ------
    ATSValidationError
        If any required field is missing or invalid.

    Checks Performed
    ----------------
    - Required fields present (job_title, company, employment_type, description)
    - Salary range is valid: salary_min <= salary_max (if both provided)
    - Employment type exists in Employment Type master
    - Department exists in Department master

    TODO: Implement required field presence check against JOB_REQUIRED_FIELDS
    TODO: Validate salary_min <= salary_max when both provided
    TODO: Validate employment_type exists via frappe.db.exists("Employment Type", ...)
    TODO: Validate department exists via frappe.db.exists("Department", ...)
    """
    pass


# ---------------------------------------------------------------------------
# Update Validation
# ---------------------------------------------------------------------------


def validate_update(data: dict, current_doc: dict) -> None:
    """Validate a Job Opening update payload.

    Parameters
    ----------
    data : dict
        Partial Job Opening fields from the API request.
    current_doc : dict
        The existing Job Opening document (for status-based rules).

    Raises
    ------
    ATSValidationError
        If the update violates business rules (e.g., editing a Closed job).

    Checks Performed
    ----------------
    - The current status allows editing (Draft or Open only)
    - Salary range is valid if both min and max are provided
    - Only editable fields are present

    TODO: Check current_doc["status"] not in [JOB_STATUS_CLOSED]
    TODO: Validate salary range
    TODO: Implement field allowlist check
    """
    pass


# ---------------------------------------------------------------------------
# Publish Validation
# ---------------------------------------------------------------------------


def validate_publish(current_doc: dict) -> None:
    """Validate that a Job Opening is ready to be published.

    Parameters
    ----------
    current_doc : dict
        The current Job Opening document.

    Raises
    ------
    ATSValidationError
        If required publishing fields are missing or the job is not in Draft status.

    Checks Performed
    ----------------
    - Current status is JOB_STATUS_DRAFT
    - Description field is non-empty
    - At least one required_skill is listed (business rule TBD)

    TODO: Check current_doc["status"] == JOB_STATUS_DRAFT
    TODO: Check description is non-empty and meets minimum length
    """
    pass
