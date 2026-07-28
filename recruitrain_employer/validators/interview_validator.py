# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.interview_validator
=====================================================

Input Validation for Interview and Interview Feedback DocType Payloads.

Validates schedule, reschedule, and feedback payloads for Interview records
before they are processed by ``InterviewService``.

All validation functions raise ``ATSValidationError`` on failure.
"""

from __future__ import annotations

from recruitrain_employer.utils.constants import (
    INTERVIEW_REQUIRED_FIELDS,
    INTERVIEW_TYPES,
    INTERVIEW_STATUS_SCHEDULED,
    INTERVIEW_STATUS_COMPLETED,
    INTERVIEW_STATUS_CANCELLED,
    FEEDBACK_RATING_MIN,
    FEEDBACK_RATING_MAX,
    FEEDBACK_RECOMMENDATION_VALUES,
)
from recruitrain_employer.utils.exceptions import ATSValidationError


# ---------------------------------------------------------------------------
# Schedule Validation
# ---------------------------------------------------------------------------


def validate_create(data: dict) -> None:
    """Validate an Interview schedule payload.

    Parameters
    ----------
    data : dict
        Raw input data from the API request.

    Raises
    ------
    ATSValidationError
        If required fields are missing or invalid.

    Checks Performed
    ----------------
    - Required fields present: application, interview_type, scheduled_on, interviewers
    - scheduled_on is a future datetime
    - interview_type is in INTERVIEW_TYPES
    - At least one interviewer is provided
    - duration_minutes is positive integer (if provided)

    TODO: Implement required field presence check against INTERVIEW_REQUIRED_FIELDS
    TODO: Validate scheduled_on > frappe.utils.now_datetime()
    TODO: Check interview_type in INTERVIEW_TYPES
    TODO: Check len(data.get("interviewers", [])) >= 1
    """
    pass


# ---------------------------------------------------------------------------
# Reschedule Validation
# ---------------------------------------------------------------------------


def validate_reschedule(data: dict, current_doc: dict) -> None:
    """Validate an Interview reschedule payload.

    Parameters
    ----------
    data : dict
        Reschedule data: scheduled_on, duration_minutes, reason.
    current_doc : dict
        The current Interview document.

    Raises
    ------
    ATSValidationError
        If the interview cannot be rescheduled or the new datetime is invalid.

    Checks Performed
    ----------------
    - Current status is INTERVIEW_STATUS_SCHEDULED
    - New scheduled_on is a future datetime
    - reason is non-empty

    TODO: Check current_doc["status"] == INTERVIEW_STATUS_SCHEDULED
    TODO: Validate new scheduled_on is future datetime
    """
    pass


# ---------------------------------------------------------------------------
# Feedback Validation
# ---------------------------------------------------------------------------


def validate_feedback(data: dict) -> None:
    """Validate an Interview Feedback submission payload.

    Parameters
    ----------
    data : dict
        Feedback data: overall_rating, recommendation, comments, etc.

    Raises
    ------
    ATSValidationError
        If rating values are out of range or recommendation is not valid.

    Checks Performed
    ----------------
    - overall_rating is between FEEDBACK_RATING_MIN and FEEDBACK_RATING_MAX
    - recommendation is in FEEDBACK_RECOMMENDATION_VALUES
    - comments is non-empty

    TODO: Validate overall_rating range
    TODO: Validate recommendation in FEEDBACK_RECOMMENDATION_VALUES
    TODO: Check optional rating fields (technical_rating, communication_rating) if provided
    """
    pass
