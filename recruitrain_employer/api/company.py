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
from recruitrain_employer.utils.exceptions import ATSException, ATSValidationError
from recruitrain_employer.utils.permissions import get_current_company
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
# Profile Endpoints (consumed by companyApi.js)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_company_profile() -> dict:
    """Return the full Company profile for the currently authenticated employer.

    Scopes to the company linked to the authenticated Employer User record.
    No ``company_id`` parameter is required — the company is resolved from
    the session via ``get_current_company()``.

    Returns
    -------
    dict
        Standardised success response containing all Company profile fields::

            {
                "success": true,
                "data": {
                    "name": "Acme Corp",
                    "company_name": "Acme Corp",
                    "logo": "/files/logo.png",
                    "banner": null,
                    "industry": "Technology",
                    ...
                }
            }
    """
    try:
        company_id = get_current_company()
        service = CompanyService()
        profile = service.get_company_profile(company_id=company_id)
        return success_response(data=profile)
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
def update_company_profile() -> dict:
    """Update the Company profile for the currently authenticated employer.

    Scopes to the company linked to the authenticated Employer User.  Accepts
    any subset of fields allowed by ``COMPANY_UPDATABLE_FIELDS``.

    Expected Request Body (JSON / form-data)
    -----------------------------------------
    Any subset of::

        {
            "legal_name": "Acme Corporation Ltd",
            "industry": "Technology",
            "phone": "+1 800 555 1234",
            "website": "https://acme.com",
            "description": "...",
            "country": "United States",
            "state": "California",
            "city": "San Francisco",
            "address_line_1": "123 Main St",
            "address_line_2": "Suite 400",
            "postal_code": "94105",
            "status": "Active",
            "company_size": "51-200",
            "linkedin": "https://linkedin.com/company/acme",
            "twitter": "https://twitter.com/acme",
            "facebook": "https://facebook.com/acme",
            "instagram": "https://instagram.com/acme"
        }

    Returns
    -------
    dict
        Standardised success response containing the updated Company document.
    """
    try:
        company_id = get_current_company()
        data = _extract_company_fields(frappe.form_dict)
        service = CompanyService()
        profile = service.update_company_profile(company_id=company_id, data=data)
        return success_response(data=profile, message="Company profile updated successfully.")
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
def upload_company_logo() -> dict:
    """Upload or replace the Company logo for the authenticated employer.

    Reads the uploaded file from the multipart request, validates MIME type
    and size, creates a Frappe File record, and updates ``Company.logo``.

    Expected Request
    ----------------
    ``Content-Type: multipart/form-data`` with a single file field named
    ``"logo"``.

    Returns
    -------
    dict
        Standardised success response::

            {
                "success": true,
                "data": {
                    "logo_url": "/files/acme-logo.png"
                }
            }
    """
    try:
        company_id = get_current_company()

        # Read the uploaded file from the multipart request.
        uploaded_file = None
        if hasattr(frappe.request, "files") and "logo" in frappe.request.files:
            uploaded_file = frappe.request.files["logo"]

        if not uploaded_file or not uploaded_file.filename:
            raise ATSValidationError(
                "No logo file was provided. Send a multipart/form-data request "
                "with a file field named 'logo'.",
                field="logo",
            )

        file_name: str = uploaded_file.filename
        file_content: bytes = uploaded_file.read()
        content_type: str = (
            uploaded_file.content_type
            or frappe.form_dict.get("content_type", "application/octet-stream")
        )

        service = CompanyService()
        result = service.upload_company_logo(
            company_id=company_id,
            file_content=file_content,
            file_name=file_name,
            content_type=content_type,
        )

        return success_response(data=result, message="Company logo uploaded successfully.")

    except ATSException as exc:
        return _handle_ats_exception(exc)



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
