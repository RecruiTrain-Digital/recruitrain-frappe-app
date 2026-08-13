# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api.jobs
================================

Job Opening API Endpoints.

Architecture
------------
This module is a **thin controller only**.  The following are strictly
prohibited here:

- ``frappe.get_doc()``
- ``frappe.get_all()``
- ``frappe.get_list()``
- ``frappe.db.*``
- Any direct DocType or ORM access

All business logic and database interactions live in ``JobService``.

Request/Response Flow::

    React
      │
      ▼
    api/jobs.py               ← Parse input, invoke service, format response
      │
      ▼
    JobService                ← Business logic, ORM queries
      │
      ▼
    JobValidator              ← Input validation
      │
      ▼
    Frappe ORM / MariaDB

Endpoint Path Prefix
---------------------
/api/method/recruitrain_employer.api.jobs.<function_name>
"""

import frappe

from recruitrain_employer.services.job_service import JobService
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
# Job Opening CRUD Endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
def save_draft(job_id: str | None = None) -> dict:
    """Save a Job Opening draft (supports create and update).

    Accepts incomplete payloads. Does NOT require mandatory publish fields
    (job_title, employment_type, job_summary).
    """
    try:
        job_id = job_id or frappe.form_dict.get("job_id") or frappe.form_dict.get("name")
        data = _extract_job_fields(frappe.form_dict, exclude={"job_id", "name"})

        service = JobService()
        job = service.save_draft(data=data, job_id=job_id)

        return success_response(data=job, message="Job Opening draft saved successfully.")

    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
def create_job() -> dict:
    """Create a new Job Opening record.

    Expected Request Body (JSON / form-data)
    -----------------------------------------
    ::

        {
            "job_title":         "Senior Python Developer",   # required for publish
            "company":           "Acme Corp",                 # required for publish
            "employment_type":   "Full-Time",                 # required for publish
            "description":       "We are looking for ...",    # required for publish
            "status":            "Draft",                     # optional (default Draft)
        }

    Returns
    -------
    dict
        Standardised success response containing the new Job Opening record,
        or an error envelope on validation/conflict failure.
    """
    try:
        data = _extract_job_fields(frappe.form_dict)

        service = JobService()
        job = service.create_job(data)

        return success_response(data=job, message="Job Opening created successfully.")

    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
def get_job(job_id: str) -> dict:
    """Retrieve a full Job Opening record by ID.

    Parameters
    ----------
    job_id : str
        The ``name`` (primary key) of the Job Opening DocType record.
        Pass as a query-string or JSON body parameter.

    Returns
    -------
    dict
        Standardised success response containing the Job Opening document,
        or an error envelope if not found.
    """
    try:
        service = JobService()
        job = service.get_job(job_id=job_id)

        return success_response(data=job)

    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
def update_job(job_id: str) -> dict:
    """Update mutable fields of an existing Job Opening record.

    Parameters
    ----------
    job_id : str
        The ``name`` of the Job Opening to update.

    Expected Request Body (JSON / form-data)
    -----------------------------------------
    Any subset of updatable Job Opening fields (see
    ``JobValidator.JOB_UPDATABLE_FIELDS``).
    ``company`` cannot be changed here.

    Returns
    -------
    dict
        Standardised success response containing the updated Job Opening
        document, or an error envelope on failure.
    """
    try:
        data = _extract_job_fields(frappe.form_dict, exclude={"job_id"})

        service = JobService()
        job = service.update_job(
            job_id=job_id,
            data=data,
        )

        return success_response(data=job, message="Job Opening updated successfully.")

    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
def delete_job(job_id: str) -> dict:
    """Delete a Job Opening record.

    Parameters
    ----------
    job_id : str
        The ``name`` of the Job Opening to delete.

    Returns
    -------
    dict
        Standardised success response on completion, or an error envelope
        if the record is not found or has blocking linked records.

    Notes
    -----
    If the Job Opening has linked Job Applications, Frappe will prevent
    deletion and a ``CONFLICT`` error is returned.  Resolve those
    references before retrying.

    TODO: Replace hard delete with archive workflow during Job Lifecycle sprint.
    """
    try:
        service = JobService()
        service.delete_job(job_id=job_id)

        return success_response(
            message=f"Job Opening '{job_id}' was deleted successfully."
        )

    except ATSException as exc:
        return _handle_ats_exception(exc)


# ---------------------------------------------------------------------------
# List & Search Endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_jobs() -> dict:
    """Return a paginated, filtered list of Job Opening records.

    Query Parameters
    ----------------
    page           : int  (default 1)
        Page number (1-indexed).
    page_size      : int  (default 20, max 100)
        Number of records per page.
    company        : str  (optional)
        Filter by Company.
    department     : str  (optional)
        Filter by Department.
    employment_type : str  (optional)
        Filter by Employment Type.
    status         : str  (optional)
        Filter by Job Opening status (Draft | Open | On Hold | Closed).
    location       : str  (optional)
        Filter by location string.
    order_by       : str  (optional, default ``"creation"``)
        Field to sort by.  Must be a whitelisted sortable field.
    order_dir      : str  (optional, default ``"desc"``)
        Sort direction — ``"asc"`` or ``"desc"``.

    Returns
    -------
    dict
        Paginated success response with ``data`` list and ``meta`` block.

    TODO: Add salary range filter parameters in a future sprint.
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

        service = JobService()
        result = service.list_jobs(
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
def search_jobs() -> dict:
    """Search Job Opening records across multiple fields.

    Searches across: job_title, job_code, department, employment_type,
    location, company.

    To add a new searchable field, update ``SEARCHABLE_FIELDS`` in
    ``JobService`` — no changes are needed here.

    Query Parameters
    ----------------
    search         : str  (required)
        The search term.  Partial matches are supported.
    page           : int  (default 1)
    page_size      : int  (default 20, max 100)
    company        : str  (optional)
        Narrow search results by company.
    department     : str  (optional)
        Narrow search results by department.
    employment_type : str  (optional)
        Narrow search results by employment type.
    status         : str  (optional)
        Narrow search results by status.
    location       : str  (optional)
        Narrow search results by location.
    order_by       : str  (optional, default ``"creation"``)
    order_dir      : str  (optional, default ``"desc"``)

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

        service = JobService()
        result = service.search_jobs(
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
# Lifecycle Endpoints (Future Sprints — stubs only)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def publish_job(job_id: str | None = None) -> dict:
    """Publish a Draft Job Opening to make it visible.

    Enforces mandatory publish fields (job_title, employment_type, job_summary, company).
    """
    try:
        job_id = job_id or frappe.form_dict.get("job_id") or frappe.form_dict.get("name")
        data = _extract_job_fields(frappe.form_dict, exclude={"job_id", "name"})

        service = JobService()
        job = service.publish_job(job_id=job_id, data=data)
        return success_response(data=job, message="Job Opening published successfully.")
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
def close_job(job_id: str) -> dict:
    """Close an active Job Opening, stopping new applications."""
    try:
        service = JobService()
        job = service.close_job(job_id=job_id)
        return success_response(data=job, message="Job Opening closed successfully.")
    except ATSException as exc:
        return _handle_ats_exception(exc)


# ---------------------------------------------------------------------------
# Private Input Helpers
# ---------------------------------------------------------------------------


def _extract_job_fields(form_dict, exclude: set[str] | None = None) -> dict:
    """Extract Job Opening field values from the Frappe form dict."""
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
    """Extract optional list/search filter parameters from the request."""
    filters: dict = {}
    filter_keys = (
        "company",
        "department",
        "profession",
        "employment_type",
        "industry",
        "status",
        "compensation_type",
        "tariff_group",
        "german_level_required",
        "allow_international_candidates",
        "allow_domestic_candidates",
        "city",
        "state",
        "country",
        "remote",
        "hybrid",
        "published",
        "featured_job",
        "location",
    )
    for key in filter_keys:
        if form_dict.get(key) is not None and form_dict.get(key) != "":
            filters[key] = form_dict[key]

    return filters

