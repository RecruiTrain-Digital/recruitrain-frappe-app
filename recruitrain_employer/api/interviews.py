# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api.interviews
======================================

Interview Scheduling API Endpoints.

Provides REST endpoints for Interview DocType operations including creation,
retrieval, update, deletion, listing, search, and status changes.

Business logic MUST NOT be implemented here — delegate to
``recruitrain_employer.services.interview_service.InterviewService``.

Endpoint Path Prefix
---------------------
/api/method/recruitrain_employer.api.interviews.<function_name>
"""

from __future__ import annotations

import frappe

from recruitrain_employer.services.interview_service import InterviewService
from recruitrain_employer.utils.constants import DEFAULT_PAGE, DEFAULT_PAGE_SIZE
from recruitrain_employer.utils.exceptions import ATSException
from recruitrain_employer.utils.response import (
    error_response,
    paginated_response,
    success_response,
)


def _handle_ats_exception(exc: ATSException) -> dict:
    """Translate an ATSException into a standardised error response dict."""
    return error_response(
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


# ---------------------------------------------------------------------------
# Interview CRUD Endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
def create_interview() -> dict:
    """Create a new Interview record."""
    try:
        data = _extract_interview_fields(frappe.form_dict)
        service = InterviewService()
        interview = service.create_interview(data)
        return success_response(
            data=interview,
            message="Interview scheduled successfully.",
        )
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
def schedule_interview() -> dict:
    """Alias for create_interview."""
    return create_interview()


@frappe.whitelist()
def get_interview(interview_id: str | None = None) -> dict:
    """Retrieve a single Interview record by ID."""
    try:
        target_id = interview_id or frappe.form_dict.get("interview_id") or frappe.form_dict.get("name")
        service = InterviewService()
        interview = service.get_interview(interview_id=target_id)
        return success_response(data=interview)
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
def update_interview(interview_id: str | None = None) -> dict:
    """Update an existing Interview record."""
    try:
        target_id = interview_id or frappe.form_dict.get("interview_id") or frappe.form_dict.get("name")
        data = _extract_interview_fields(
            frappe.form_dict, exclude={"interview_id", "name"}
        )
        service = InterviewService()
        interview = service.update_interview(interview_id=target_id, data=data)
        return success_response(
            data=interview,
            message="Interview updated successfully.",
        )
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
def delete_interview(interview_id: str | None = None) -> dict:
    """Delete an Interview record."""
    try:
        target_id = interview_id or frappe.form_dict.get("interview_id") or frappe.form_dict.get("name")
        service = InterviewService()
        service.delete_interview(interview_id=target_id)
        return success_response(
            message=f"Interview '{target_id}' was deleted successfully."
        )
    except ATSException as exc:
        return _handle_ats_exception(exc)


# ---------------------------------------------------------------------------
# Status Management Endpoint
# ---------------------------------------------------------------------------


@frappe.whitelist()
def change_status(interview_id: str | None = None, new_status: str | None = None) -> dict:
    """Change the status of an Interview.

    Allowed status values: Scheduled | Rescheduled | Completed | Cancelled | No Show
    """
    try:
        target_id = interview_id or frappe.form_dict.get("interview_id") or frappe.form_dict.get("name")
        status_val = new_status or frappe.form_dict.get("new_status") or frappe.form_dict.get("status")

        service = InterviewService()
        interview = service.change_status(
            interview_id=target_id,
            new_status=status_val,
        )
        return success_response(
            data=interview,
            message=f"Interview status updated to '{status_val}'.",
        )
    except ATSException as exc:
        return _handle_ats_exception(exc)


# ---------------------------------------------------------------------------
# List & Search Endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_interviews() -> dict:
    """Return a paginated list of Interviews."""
    try:
        page = int(frappe.form_dict.get("page", DEFAULT_PAGE))
        page_size = int(frappe.form_dict.get("page_size", DEFAULT_PAGE_SIZE))
        order_by = frappe.form_dict.get("order_by", "creation")
        order_dir = frappe.form_dict.get("order_dir", "desc")

        filters = _extract_list_filters(frappe.form_dict)

        service = InterviewService()
        result = service.list_interviews(
            page=page,
            page_size=page_size,
            filters=filters,
            order_by=order_by,
            order_dir=order_dir,
        )

        return paginated_response(
            data=result["data"],
            page=result["page"],
            page_size=result["page_size"],
            total=result["total"],
        )
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
def search_interviews() -> dict:
    """Search Interview records across candidate, company, job_opening, interviewer, scheduled_on, status."""
    try:
        search = frappe.form_dict.get("search", "").strip()
        page = int(frappe.form_dict.get("page", DEFAULT_PAGE))
        page_size = int(frappe.form_dict.get("page_size", DEFAULT_PAGE_SIZE))
        order_by = frappe.form_dict.get("order_by", "creation")
        order_dir = frappe.form_dict.get("order_dir", "desc")

        filters = _extract_list_filters(frappe.form_dict)

        service = InterviewService()
        result = service.search_interviews(
            search=search,
            page=page,
            page_size=page_size,
            filters=filters,
            order_by=order_by,
            order_dir=order_dir,
        )

        return paginated_response(
            data=result["data"],
            page=result["page"],
            page_size=result["page_size"],
            total=result["total"],
        )
    except ATSException as exc:
        return _handle_ats_exception(exc)


# ---------------------------------------------------------------------------
# Private Helpers
# ---------------------------------------------------------------------------


def _extract_interview_fields(
    form_dict, exclude: set[str] | None = None
) -> dict:
    """Extract interview fields from frappe.form_dict."""
    _FRAPPE_INTERNAL_KEYS: frozenset[str] = frozenset(
        ["cmd", "csrf_token", "doctype", "docname"]
    )
    skip = _FRAPPE_INTERNAL_KEYS | (exclude or set())
    return {
        key: value
        for key, value in form_dict.items()
        if key not in skip and value not in (None, "")
    }


def _extract_list_filters(form_dict) -> dict:
    """Extract filter parameters from form_dict."""
    filters: dict = {}

    for key in (
        "job_application",
        "candidate",
        "company",
        "job_opening",
        "interviewer",
        "scheduled_on",
        "status",
        "interview_type",
    ):
        if form_dict.get(key):
            filters[key] = form_dict[key]

    return filters
