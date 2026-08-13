# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api.job_application
=========================================

Job Application API Endpoints.

Architecture
------------
This module is a **thin controller only**.  The following are strictly
prohibited here:

- ``frappe.get_doc()``
- ``frappe.get_all()``
- ``frappe.get_list()``
- ``frappe.db.*``
- Any direct DocType or ORM access

All business logic and database interactions live in ``JobApplicationService``.

Request/Response Flow::

    React
      │
      ▼
    api/job_application.py        ← Parse input, invoke service, format response
      │
      ▼
    JobApplicationService         ← Business logic, ORM queries
      │
      ▼
    JobApplicationValidator       ← Input validation
      │
      ▼
    Frappe ORM / MariaDB

Endpoint Path Prefix
---------------------
/api/method/recruitrain_employer.api.job_application.<function_name>
"""

import frappe

from recruitrain_employer.services.job_application_service import (
    JobApplicationService,
)
from recruitrain_employer.utils.constants import DEFAULT_PAGE, DEFAULT_PAGE_SIZE
from recruitrain_employer.utils.exceptions import (
    ATSConflictError,
    ATSException,
    ATSPermissionError,
)
from recruitrain_employer.utils.permissions import employer_required
from recruitrain_employer.utils.response import (
    error_response,
    paginated_response,
    success_response,
)


STATUS_CODE_MAP: dict[str, int] = {
    "VALIDATION_ERROR": 400,
    "NOT_FOUND": 404,
    "PERMISSION_DENIED": 403,
    "COMPANY_NOT_FOUND": 403,
    "CONFLICT": 409,
    "UNAUTHORIZED": 401,
}


# ---------------------------------------------------------------------------
# Internal Helper
# ---------------------------------------------------------------------------


def _handle_ats_exception(exc: Exception) -> dict:
    """Translate an ATSException or Frappe Exception into a standardised error response dict."""
    if isinstance(exc, ATSPermissionError):
        msg = getattr(exc, "message", None) or str(exc)
        status_code = 401 if ("Authentication" in msg or "log in" in msg) else 403
        return error_response(
            code=getattr(exc, "code", "PERMISSION_DENIED"),
            message=msg,
            details=getattr(exc, "details", None),
            http_status_code=status_code,
        )
    if isinstance(exc, (ATSConflictError, frappe.exceptions.DuplicateEntryError, frappe.exceptions.TimestampMismatchError)):
        msg = getattr(exc, "message", None) or str(exc)
        if isinstance(exc, frappe.exceptions.TimestampMismatchError):
            msg = "This record has been modified by another user. Please reload and try again."
        return error_response(
            code="CONFLICT",
            message=msg,
            details=getattr(exc, "details", None),
            http_status_code=409,
        )
    if isinstance(exc, ATSException):
        return error_response(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            http_status_code=STATUS_CODE_MAP.get(exc.code, 400),
        )
    return error_response(
        code="INTERNAL_SERVER_ERROR",
        message="An error occurred while processing job application request.",
        details={"error": str(exc)},
        http_status_code=500,
    )



# ---------------------------------------------------------------------------
# Job Application CRUD Endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
@employer_required
def create_application() -> dict:
    """Submit a new Job Application."""
    try:
        data = _extract_application_fields(frappe.form_dict)

        service = JobApplicationService()
        application = service.create_application(data)

        return success_response(
            data=application,
            message="Job Application submitted successfully.",
        )

    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_application(application_id: str | None = None) -> dict:
    """Retrieve a full Job Application record by ID."""
    try:
        target_id = application_id or frappe.form_dict.get("application_id") or frappe.form_dict.get("name")
        service = JobApplicationService()
        application = service.get_application(application_id=target_id)

        return success_response(data=application)

    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def update_application(application_id: str | None = None) -> dict:
    """Update mutable fields of an existing Job Application record."""
    try:
        target_id = application_id or frappe.form_dict.get("application_id") or frappe.form_dict.get("name")
        data = _extract_application_fields(
            frappe.form_dict, exclude={"application_id", "name"}
        )

        service = JobApplicationService()
        application = service.update_application(
            application_id=target_id,
            data=data,
        )

        return success_response(
            data=application,
            message="Job Application updated successfully.",
        )

    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def delete_application(application_id: str | None = None) -> dict:
    """Delete a Job Application record."""
    try:
        target_id = application_id or frappe.form_dict.get("application_id") or frappe.form_dict.get("name")
        service = JobApplicationService()
        service.delete_application(application_id=target_id)

        return success_response(
            message=f"Job Application '{target_id}' was deleted successfully."
        )

    except ATSException as exc:
        return _handle_ats_exception(exc)


# ---------------------------------------------------------------------------
# Status Management Endpoint
# ---------------------------------------------------------------------------


@frappe.whitelist()
@employer_required
def change_status(application_id: str | None = None, new_status: str | None = None) -> dict:
    """Change the status of a Job Application."""
    try:
        target_id = application_id or frappe.form_dict.get("application_id") or frappe.form_dict.get("name")
        status_val = new_status or frappe.form_dict.get("new_status") or frappe.form_dict.get("status")

        service = JobApplicationService()
        application = service.change_status(
            application_id=target_id,
            new_status=status_val,
        )

        return success_response(
            data=application,
            message=f"Application status updated to '{status_val}'.",
        )

    except ATSException as exc:
        return _handle_ats_exception(exc)


# ---------------------------------------------------------------------------
# List & Search Endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
@employer_required
def list_applications() -> dict:
    """Return a paginated, filtered list of Job Application records."""
    try:
        page = int(frappe.form_dict.get("page", DEFAULT_PAGE))
        page_size = int(frappe.form_dict.get("page_size", DEFAULT_PAGE_SIZE))
        order_by = frappe.form_dict.get("order_by", "creation")
        order_dir = frappe.form_dict.get("order_dir", "desc")

        filters = _extract_list_filters(frappe.form_dict)

        service = JobApplicationService()
        result = service.list_applications(
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
@employer_required
def search_applications() -> dict:
    """Search Job Application records across multiple fields."""
    try:
        search = frappe.form_dict.get("search", "").strip()
        page = int(frappe.form_dict.get("page", DEFAULT_PAGE))
        page_size = int(frappe.form_dict.get("page_size", DEFAULT_PAGE_SIZE))
        order_by = frappe.form_dict.get("order_by", "creation")
        order_dir = frappe.form_dict.get("order_dir", "desc")

        filters = _extract_list_filters(frappe.form_dict)

        service = JobApplicationService()
        result = service.search_applications(
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
# Out-of-Scope Lifecycle Endpoints (stubs — future sprints)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def schedule_interview(application_id: str) -> dict:
    """Schedule an Interview for a Job Application.

    """
    return error_response(
        code="NOT_IMPLEMENTED",
        message="Interview scheduling is not yet available.",
    )


@frappe.whitelist()
def generate_offer(application_id: str) -> dict:
    """Generate an Offer for a hired Job Application.

    """
    return error_response(
        code="NOT_IMPLEMENTED",
        message="Offer generation is not yet available.",
    )


# ---------------------------------------------------------------------------
# Private Input Helpers
# ---------------------------------------------------------------------------


def _extract_application_fields(
    form_dict, exclude: set[str] | None = None
) -> dict:
    """Extract Job Application field values from the Frappe form dict.

    Strips ``frappe.form_dict`` keys that are internal Frappe parameters
    (``cmd``, ``csrf_token``, etc.) and any caller-specified ``exclude``
    keys, returning only the fields that belong to the Job Application payload.

    Parameters
    ----------
    form_dict : frappe.local.form_dict
        The raw request parameters dict.
    exclude : set[str] or None, optional
        Additional keys to exclude from the output (e.g. ``{"application_id"}``
        when the ID is a path parameter rather than a body field).

    Returns
    -------
    dict
        A clean dict of job application field key/value pairs.
    """
    # Keys injected by Frappe's request handling — never application data.
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
    """Extract optional list/search filter parameters from the request.

    Centralises filter extraction so that adding a new filter parameter
    only requires a change here and in ``JobApplicationService._build_filters``,
    not in each endpoint that calls ``list_applications`` or
    ``search_applications``.

    Parameters
    ----------
    form_dict : frappe.local.form_dict
        The raw request parameters dict.

    Returns
    -------
    dict
        A filter map ready to be passed to
        ``JobApplicationService.list_applications`` or
        ``JobApplicationService.search_applications``.

    """
    filters: dict = {}

    if form_dict.get("candidate"):
        filters["candidate"] = form_dict["candidate"]

    if form_dict.get("job_opening"):
        filters["job_opening"] = form_dict["job_opening"]

    if form_dict.get("company"):
        filters["company"] = form_dict["company"]

    if form_dict.get("status"):
        filters["status"] = form_dict["status"]

    if form_dict.get("application_date"):
        filters["application_date"] = form_dict["application_date"]

    return filters
