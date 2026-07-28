# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api.company
==================================

Company API Endpoints.

Architecture
------------
This module is a **thin controller only**.  The following are strictly
prohibited here:

- ``frappe.get_doc()``
- ``frappe.get_all()``
- ``frappe.get_list()``
- ``frappe.db.*``
- Any direct DocType or ORM access

All business logic and database interactions live in ``CompanyService``.

Request/Response Flow::

    React
      │
      ▼
    api/company.py            ← Parse input, invoke service, format response
      │
      ▼
    CompanyService            ← Business logic, ORM queries
      │
      ▼
    CompanyValidator          ← Normalization + validation
      │
      ▼
    Frappe ORM / MariaDB

Endpoint Path Prefix
---------------------
/api/method/recruitrain_employer.api.company.<function_name>
"""

import frappe

from recruitrain_employer.services.company_service import CompanyService
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
# Company CRUD Endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
def create_company() -> dict:
    """Create a new Company record.

    Expected Request Body (JSON / form-data)
    -----------------------------------------
    ::

        {
            "company_name": "Acme Corp",          # required
            "industry": "Technology",             # required
            "email": "info@acme.com",             # optional
            "phone": "+1 800 555 1234",           # optional
            "website": "https://acme.com",        # optional
            "description": "...",                 # optional
            "country": "United States",           # optional
            "state": "California",                # optional
            "city": "San Francisco",              # optional
            "address": "123 Main St",             # optional
            "postal_code": "94105",               # optional
            "founded_year": 2010,                 # optional
            "company_size": "51-200",             # optional
            "linkedin_url": "https://linkedin.com/company/acme",  # optional
            "twitter_url": "https://twitter.com/acme"             # optional
        }

    Returns
    -------
    dict
        Standardised success response containing the new Company record,
        or an error envelope on validation/conflict failure.
    """
    try:
        data = _extract_company_fields(frappe.form_dict)

        service = CompanyService()
        company = service.create_company(data)

        return success_response(data=company, message="Company created successfully.")

    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
def get_company(company_id: str) -> dict:
    """Retrieve a full Company profile by ID.

    Parameters
    ----------
    company_id : str
        The ``name`` (primary key) of the Company DocType record.
        Pass as a query-string or JSON body parameter.

    Returns
    -------
    dict
        Standardised success response containing the Company document,
        or an error envelope if not found.
    """
    try:
        service = CompanyService()
        company = service.get_company(company_id=company_id)

        return success_response(data=company)

    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
def update_company(company_id: str) -> dict:
    """Update mutable fields of an existing Company record.

    Parameters
    ----------
    company_id : str
        The ``name`` of the Company to update.

    Expected Request Body (JSON / form-data)
    -----------------------------------------
    Any subset of updatable Company fields (see
    ``CompanyValidator.COMPANY_UPDATABLE_FIELDS``).
    ``company_name`` and ``email`` cannot be changed here.

    Returns
    -------
    dict
        Standardised success response containing the updated Company
        document, or an error envelope on failure.
    """
    try:
        data = _extract_company_fields(
            frappe.form_dict, exclude={"company_id"}
        )

        service = CompanyService()
        company = service.update_company(
            company_id=company_id,
            data=data,
        )

        return success_response(data=company, message="Company updated successfully.")

    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
def delete_company(company_id: str) -> dict:
    """Delete a Company record.

    Parameters
    ----------
    company_id : str
        The ``name`` of the Company to delete.

    Returns
    -------
    dict
        Standardised success response on completion, or an error envelope
        if the record is not found or has blocking linked records.

    Notes
    -----
    If the Company has linked Job Openings or Employer Users, Frappe will
    prevent deletion and a ``CONFLICT`` error is returned.  Resolve those
    references before retrying.
    """
    try:
        service = CompanyService()
        service.delete_company(company_id=company_id)

        return success_response(
            message=f"Company '{company_id}' was deleted successfully."
        )

    except ATSException as exc:
        return _handle_ats_exception(exc)


# ---------------------------------------------------------------------------
# List & Search Endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_companies() -> dict:
    """Return a paginated, filtered list of Company records.

    Query Parameters
    ----------------
    page       : int  (default 1)
        Page number (1-indexed).
    page_size  : int  (default 20, max 100)
        Number of records per page.
    industry   : str  (optional)
        Filter by Industry value.
    status     : str  (optional)
        Filter by Company status.
    country    : str  (optional)
        Filter by country.
    state      : str  (optional)
        Filter by state/region.
    city       : str  (optional)
        Filter by city.
    order_by   : str  (optional, default ``"creation"``)
        Field to sort by.  Must be a whitelisted sortable field.
    order_dir  : str  (optional, default ``"desc"``)
        Sort direction — ``"asc"`` or ``"desc"``.

    Returns
    -------
    dict
        Paginated success response with ``data`` list and ``meta`` block.

    TODO: Add company_size filter parameter in a future sprint.
    """
    try:
        page = int(frappe.form_dict.get("page", DEFAULT_PAGE))
        page_size = int(frappe.form_dict.get("page_size", DEFAULT_PAGE_SIZE))
        order_by = frappe.form_dict.get("order_by", "creation")
        order_dir = frappe.form_dict.get("order_dir", "desc")

        filters = _extract_list_filters(frappe.form_dict)

        service = CompanyService()
        result = service.list_companies(
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
def search_companies() -> dict:
    """Search Company records across multiple fields.

    Searches across: company_name, email, phone, website, industry,
    city, country.

    To add a new searchable field, update ``SEARCHABLE_FIELDS`` in
    ``CompanyService`` — no changes needed here.

    Query Parameters
    ----------------
    search     : str  (required)
        The search term.  Partial matches are supported.
    page       : int  (default 1)
    page_size  : int  (default 20, max 100)
    industry   : str  (optional)
        Narrow search results by industry.
    status     : str  (optional)
        Narrow search results by status.
    country    : str  (optional)
        Narrow search results by country.
    order_by   : str  (optional, default ``"creation"``)
    order_dir  : str  (optional, default ``"desc"``)

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

        service = CompanyService()
        result = service.search_companies(
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
# Sub-Resource Endpoints (Future Sprints — stubs only)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_company_jobs(company_id: str) -> dict:
    """List all active Job Openings belonging to a Company.

    TODO: Implement in the Job Opening sprint.
    TODO: Delegate to CompanyService.get_company_jobs().
    """
    return error_response(
        code="NOT_IMPLEMENTED",
        message="Company Job Openings retrieval is not yet available.",
    )


@frappe.whitelist()
def get_company_stats(company_id: str) -> dict:
    """Return high-level statistics for a Company.

    TODO: Implement in the Dashboard/Analytics sprint.
    TODO: Delegate to CompanyService.get_company_stats().
    """
    return error_response(
        code="NOT_IMPLEMENTED",
        message="Company statistics are not yet available.",
    )


@frappe.whitelist()
def upload_company_logo(company_id: str) -> dict:
    """Upload or replace the Company logo.

    TODO: Implement in the Logo Upload sprint.
    TODO: Validate MIME type and size via CompanyValidator.validate_logo_upload().
    TODO: Delegate to CompanyService.upload_company_logo().
    """
    return error_response(
        code="NOT_IMPLEMENTED",
        message="Company logo upload is not yet available.",
    )


# ---------------------------------------------------------------------------
# Private Input Helpers
# ---------------------------------------------------------------------------


def _extract_company_fields(form_dict, exclude: set[str] | None = None) -> dict:
    """Extract Company field values from the Frappe form dict.

    Strips Frappe internal parameters (``cmd``, ``csrf_token``, etc.) and
    any caller-specified ``exclude`` keys, returning only fields that belong
    to the Company payload.

    Parameters
    ----------
    form_dict : frappe.local.form_dict
        The raw request parameters dict.
    exclude : set[str] or None, optional
        Additional keys to exclude (e.g. ``{"company_id"}`` when the ID is
        a path parameter rather than a body field).

    Returns
    -------
    dict
        A clean dict of company field key/value pairs.
    """
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
    (e.g. ``company_size``) only requires a change here and in
    ``CompanyService._build_orm_filters`` — not in each endpoint.

    Parameters
    ----------
    form_dict : frappe.local.form_dict
        The raw request parameters dict.

    Returns
    -------
    dict
        A filter map ready for ``CompanyService.list_companies`` or
        ``CompanyService.search_companies``.

    TODO: Add company_size filter when needed.
    """
    filters: dict = {}

    if form_dict.get("industry"):
        filters["industry"] = form_dict["industry"]

    if form_dict.get("status"):
        filters["status"] = form_dict["status"]

    if form_dict.get("country"):
        filters["country"] = form_dict["country"]

    if form_dict.get("state"):
        filters["state"] = form_dict["state"]

    if form_dict.get("city"):
        filters["city"] = form_dict["city"]

    return filters
