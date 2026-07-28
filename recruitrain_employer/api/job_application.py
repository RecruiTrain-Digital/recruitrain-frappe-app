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
from recruitrain_employer.utils.exceptions import ATSException
from recruitrain_employer.utils.response import (
    error_response,
    paginated_response,
    success_response,
)


# ---------------------------------------------------------------------------
# Internal Helper
# ---------------------------------------------------------------------------


def _handle_ats_exception(exc: ATSException) -> dict:
    """Translate an ``ATSException`` into a standardised error response dict.

    Parameters
    ----------
    exc : ATSException
        Any exception from the ATS exception hierarchy.

    Returns
    -------
    dict
        A standardised ``error_response`` dict.
    """
    return error_response(
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


# ---------------------------------------------------------------------------
# Job Application CRUD Endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
def create_application() -> dict:
    """Submit a new Job Application.

    Expected Request Body (JSON / form-data)
    -----------------------------------------
    ::

        {
            "job_opening":      "JOB-0001",          # required
            "candidate":        "CAND-0001",          # required
            "cover_letter":     "I am writing ...",   # optional
            "resume":           "/files/resume.pdf",  # optional
            "application_date": "2024-02-01",         # optional
            "status":           "Applied",            # optional
            "notes":            "Referred by ...",    # optional
        }

    Returns
    -------
    dict
        Standardised success response containing the new Job Application record,
        or an error envelope on validation/conflict failure.

    Notes
    -----
    Duplicate applications (same ``candidate`` + ``job_opening``) are
    rejected with a ``CONFLICT`` error.
    """
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
def get_application(application_id: str) -> dict:
    """Retrieve a full Job Application record by ID.

    Parameters
    ----------
    application_id : str
        The ``name`` (primary key) of the Job Application DocType record.
        Pass as a query-string or JSON body parameter.

    Returns
    -------
    dict
        Standardised success response containing the Job Application document,
        or an error envelope if not found.
    """
    try:
        service = JobApplicationService()
        application = service.get_application(application_id=application_id)

        return success_response(data=application)

    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
def update_application(application_id: str) -> dict:
    """Update mutable fields of an existing Job Application record.

    Parameters
    ----------
    application_id : str
        The ``name`` of the Job Application to update.

    Expected Request Body (JSON / form-data)
    -----------------------------------------
    Any subset of updatable Job Application fields (see
    ``JobApplicationValidator.APPLICATION_UPDATABLE_FIELDS``).
    ``candidate`` and ``job_opening`` cannot be changed here.

    Returns
    -------
    dict
        Standardised success response containing the updated Job Application
        document, or an error envelope on failure.
    """
    try:
        data = _extract_application_fields(
            frappe.form_dict, exclude={"application_id"}
        )

        service = JobApplicationService()
        application = service.update_application(
            application_id=application_id,
            data=data,
        )

        return success_response(
            data=application,
            message="Job Application updated successfully.",
        )

    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
def delete_application(application_id: str) -> dict:
    """Delete a Job Application record.

    Parameters
    ----------
    application_id : str
        The ``name`` of the Job Application to delete.

    Returns
    -------
    dict
        Standardised success response on completion, or an error envelope
        if the record is not found or has blocking linked records.

    Notes
    -----
    If the Job Application has linked Interviews or Offers, Frappe will
    prevent deletion and a ``CONFLICT`` error is returned.  Resolve those
    references before retrying.

    TODO: Replace hard delete with archive workflow during Application Lifecycle sprint.
    """
    try:
        service = JobApplicationService()
        service.delete_application(application_id=application_id)

        return success_response(
            message=f"Job Application '{application_id}' was deleted successfully."
        )

    except ATSException as exc:
        return _handle_ats_exception(exc)


# ---------------------------------------------------------------------------
# Status Management Endpoint
# ---------------------------------------------------------------------------


@frappe.whitelist()
def change_status(application_id: str, new_status: str) -> dict:
    """Change the status of a Job Application.

    Parameters
    ----------
    application_id : str
        The ``name`` of the Job Application to update.
    new_status : str
        The new status value.  Must be in ``ALLOWED_APPLICATION_STATUSES``:

        Applied | Screening | Shortlisted | Interview Scheduled |
        Interviewed | Offer Extended | Hired | Rejected | Withdrawn

    Returns
    -------
    dict
        Standardised success response containing the updated Job Application
        document, or an error envelope on failure.

    Notes
    -----
    Status transition rules (forward-only, terminal-stage blocking) are
    deferred to the Application Lifecycle sprint.  This endpoint currently
    accepts any valid status value regardless of the current status.

    TODO: Add transition validation in Application Lifecycle sprint.
    """
    try:
        service = JobApplicationService()
        application = service.change_status(
            application_id=application_id,
            new_status=new_status,
        )

        return success_response(
            data=application,
            message=f"Application status updated to '{new_status}'.",
        )

    except ATSException as exc:
        return _handle_ats_exception(exc)


# ---------------------------------------------------------------------------
# List & Search Endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_applications() -> dict:
    """Return a paginated, filtered list of Job Application records.

    Query Parameters
    ----------------
    page             : int  (default 1)
        Page number (1-indexed).
    page_size        : int  (default 20, max 100)
        Number of records per page.
    candidate        : str  (optional)
        Filter by Candidate ID.
    job_opening      : str  (optional)
        Filter by Job Opening ID.
    company          : str  (optional)
        Filter by Company.
    status           : str  (optional)
        Filter by application status.
    application_date : str  (optional)
        Filter by exact application date (YYYY-MM-DD).
    order_by         : str  (optional, default ``"creation"``)
        Field to sort by.  Must be a whitelisted sortable field.
    order_dir        : str  (optional, default ``"desc"``)
        Sort direction — ``"asc"`` or ``"desc"``.

    Returns
    -------
    dict
        Paginated success response with ``data`` list and ``meta`` block.

    TODO: Add date-range filter parameters in a future sprint.
    TODO: Add employer-scoped filtering once Employer–Company linking is defined.
    """
    try:
        page = int(frappe.form_dict.get("page", DEFAULT_PAGE))
        page_size = int(frappe.form_dict.get("page_size", DEFAULT_PAGE_SIZE))
        order_by = frappe.form_dict.get("order_by", "creation")
        order_dir = frappe.form_dict.get("order_dir", "desc")

        # Build the extensible filter map — add new keys here as new
        # filter parameters are added to the API.
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
def search_applications() -> dict:
    """Search Job Application records across multiple fields.

    Searches across: candidate, job_opening, name (application ID),
    status, company.

    To add a new searchable field, update ``SEARCHABLE_FIELDS`` in
    ``JobApplicationService`` — no changes are needed here.

    Query Parameters
    ----------------
    search           : str  (required)
        The search term.  Partial matches are supported.
    page             : int  (default 1)
    page_size        : int  (default 20, max 100)
    candidate        : str  (optional)
        Narrow search results by candidate.
    job_opening      : str  (optional)
        Narrow search results by job opening.
    company          : str  (optional)
        Narrow search results by company.
    status           : str  (optional)
        Narrow search results by status.
    application_date : str  (optional)
        Narrow search results by exact application date.
    order_by         : str  (optional, default ``"creation"``)
    order_dir        : str  (optional, default ``"desc"``)

    Returns
    -------
    dict
        Paginated success response with ``data`` list and ``meta`` block,
        or an error envelope if the search term is missing.
    """
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

    TODO: Implement in the Interview Scheduling sprint.
    TODO: Delegate to InterviewService.create_interview().
    """
    return error_response(
        code="NOT_IMPLEMENTED",
        message="Interview scheduling is not yet available.",
    )


@frappe.whitelist()
def generate_offer(application_id: str) -> dict:
    """Generate an Offer for a hired Job Application.

    TODO: Implement in the Offer Generation sprint.
    TODO: Delegate to OfferService.create_offer().
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

    TODO: Add date-range filter (application_date_from / application_date_to).
    TODO: Add employer-scoped filter once Employer–Company linking is defined.
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
