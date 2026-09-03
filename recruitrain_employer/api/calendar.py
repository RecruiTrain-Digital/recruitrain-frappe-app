# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api.calendar
====================================

Calendar API Endpoints for RecruitTrain Employer ATS.

Provides REST endpoints for retrieving real recruitment calendar events
derived from MariaDB records (Interview, Offer, Job Opening, Job Application).
"""

from __future__ import annotations

import frappe

from recruitrain_employer.services.calendar_service import CalendarService
from recruitrain_employer.utils.exceptions import ATSException
from recruitrain_employer.utils.permissions import employer_required, get_current_company
from recruitrain_employer.utils.response import error_response, success_response


def _handle_ats_exception(exc: Exception) -> dict:
    """Translate an ATSException or Frappe Exception into a standardised error response dict."""
    if isinstance(exc, ATSException):
        return error_response(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            http_status_code=400 if exc.code == "VALIDATION_ERROR" else 404 if exc.code == "NOT_FOUND" else 403 if exc.code == "PERMISSION_DENIED" else 400,
        )
    return error_response(
        code="INTERNAL_SERVER_ERROR",
        message="An error occurred while processing calendar request.",
        details={"error": str(exc)},
        http_status_code=500,
    )


@frappe.whitelist()
@employer_required
def get_calendar_events() -> dict:
    """
    Retrieve real recruitment calendar events for the authenticated company.

    Supported Query Parameters:
    - from_date: YYYY-MM-DD
    - to_date: YYYY-MM-DD
    - event_type: interview, offer, job_closing, application_date, etc.
    - status: Scheduled, Open, Sent, Accepted, etc.

    Note: Client-provided company overrides in form_dict are strictly ignored.
    """
    try:
        # Enforce session company scope exclusively
        company = get_current_company()

        # Extract filters
        from_date = frappe.form_dict.get("from_date")
        to_date = frappe.form_dict.get("to_date")
        event_type = frappe.form_dict.get("event_type")
        status = frappe.form_dict.get("status")

        service = CalendarService()
        events = service.get_calendar_events(
            company=company,
            from_date=from_date,
            to_date=to_date,
            event_type=event_type,
            status=status,
        )

        return success_response(
            data=events,
            message="Calendar events retrieved successfully.",
        )
    except Exception as exc:
        return _handle_ats_exception(exc)
