# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api.candidate
====================================

Candidate Profile API Endpoints.

Architecture
------------
This module is a **thin controller only**. The following are strictly
prohibited here:

- ``frappe.get_doc()``
- ``frappe.get_all()``
- ``frappe.get_list()``
- ``frappe.db.*``
- Any direct DocType or ORM access

All business logic and database interactions live in ``CandidateService``.

Request/Response Flow::

    React
      │
      ▼
    api/candidate.py          ← Parse input, invoke service, format response
      │
      ▼
    CandidateService          ← Business logic, ORM queries
      │
      ▼
    CandidateValidator        ← Input validation
      │
      ▼
    Frappe ORM / MariaDB

Endpoint Path Prefix
---------------------
/api/method/recruitrain_employer.api.candidate.<function_name>
"""

import frappe

from recruitrain_employer.services.candidate_service import CandidateService
from recruitrain_employer.utils.constants import DEFAULT_PAGE, DEFAULT_PAGE_SIZE
from recruitrain_employer.utils.exceptions import ATSException
from recruitrain_employer.utils.permissions import employer_required
from recruitrain_employer.utils.response import (
    error_response,
    paginated_response,
    success_response,
)


# ---------------------------------------------------------------------------
# Internal Helper
# ---------------------------------------------------------------------------


def _handle_ats_exception(exc: ATSException) -> dict:
    """Translate an ``ATSException`` into a standardised error response dict."""
    return error_response(
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


def _get_payload() -> dict:
    """Safely extract payload from request JSON, form_dict, or fallback."""
    req_data = None
    if getattr(frappe, "request", None):
        try:
            req_data = frappe.request.get_json()
        except Exception:
            pass
    if req_data and isinstance(req_data, dict):
        return dict(req_data)
    form = getattr(frappe, "form_dict", None)
    if form and isinstance(form, dict):
        return dict(form)
    return {}


# ---------------------------------------------------------------------------
# Candidate CRUD Endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
def create_candidate() -> dict:
    """Create a new Candidate record.

    Expected Request Body (JSON / form-data)
    -----------------------------------------
    ::

        {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane.doe@example.com",
            "phone": "+1 555 123 4567",          # optional
            "profession": "Software Engineer",    # optional
            "current_location": "Berlin, DE",     # optional
            "bio": "...",                          # optional
            "linkedin_url": "https://...",         # optional
            "portfolio_url": "https://...",        # optional
            "status": "Active"                     # optional
        }

    Returns
    -------
    dict
        Standardised success response containing the new Candidate record,
        or an error envelope on validation/conflict failure.
    """
    try:
        data = _extract_candidate_fields(frappe.form_dict)

        service = CandidateService()
        candidate = service.create_candidate(data)

        return success_response(data=candidate, message="Candidate created successfully.")

    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
def get_candidate(candidate_id: str) -> dict:
    """Retrieve a full Candidate profile by ID.

    Parameters
    ----------
    candidate_id : str
        The ``name`` (primary key) of the Candidate DocType record.
        Pass as a query-string or JSON body parameter.

    Returns
    -------
    dict
        Standardised success response containing the Candidate document,
        or an error envelope if not found.
    """
    try:
        service = CandidateService()
        candidate = service.get_candidate(candidate_id=candidate_id)

        return success_response(data=candidate)

    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
def update_candidate(candidate_id: str) -> dict:
    """Update mutable fields of an existing Candidate record.

    Parameters
    ----------
    candidate_id : str
        The ``name`` of the Candidate to update.

    Expected Request Body (JSON / form-data)
    -----------------------------------------
    Any subset of updatable Candidate fields (see
    ``CandidateValidator.CANDIDATE_UPDATABLE_FIELDS``).
    Email cannot be changed here — use the dedicated email-change flow.

    Returns
    -------
    dict
        Standardised success response containing the updated Candidate
        document, or an error envelope on failure.
    """
    try:
        data = _extract_candidate_fields(frappe.form_dict, exclude={"candidate_id"})

        service = CandidateService()
        candidate = service.update_candidate(
            candidate_id=candidate_id,
            data=data,
        )

        return success_response(data=candidate, message="Candidate updated successfully.")

    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
def delete_candidate(candidate_id: str) -> dict:
    """Delete a Candidate record.

    Parameters
    ----------
    candidate_id : str
        The ``name`` of the Candidate to delete.

    Returns
    -------
    dict
        Standardised success response on completion, or an error envelope
        if the record is not found or has blocking linked records.

    Notes
    -----
    If the Candidate has linked Job Applications, Interviews, or Offers,
    Frappe will prevent deletion and a ``CONFLICT`` error is returned.
    Resolve those references before retrying.
    """
    try:
        service = CandidateService()
        service.delete_candidate(candidate_id=candidate_id)

        return success_response(
            message=f"Candidate '{candidate_id}' was deleted successfully."
        )

    except ATSException as exc:
        return _handle_ats_exception(exc)


# ---------------------------------------------------------------------------
# List & Search Endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_candidates() -> dict:
    """Return a paginated, filtered list of Candidate records.

    Query Parameters
    ----------------
    page       : int  (default 1)
        Page number (1-indexed).
    page_size  : int  (default 20, max 100)
        Number of records per page.
    status     : str  (optional)
        Filter by Candidate ``status`` field (e.g. ``"Active"``).
    order_by   : str  (optional, default ``"creation"``)
        Field to sort by.  Must be a whitelisted sortable field.
    order_dir  : str  (optional, default ``"desc"``)
        Sort direction — ``"asc"`` or ``"desc"``.

    Returns
    -------
    dict
        Paginated success response with ``data`` list and ``meta`` block.

    TODO: Add profession, location, experience-level filter parameters.
    TODO: Add company-scoped filtering once Employer–Candidate linking is defined.
    """
    try:
        page = int(frappe.form_dict.get("page", DEFAULT_PAGE))
        page_size = int(frappe.form_dict.get("page_size", DEFAULT_PAGE_SIZE))
        order_by = frappe.form_dict.get("order_by", "creation")
        order_dir = frappe.form_dict.get("order_dir", "desc")

        # Build the extensible filter map — add new keys here as new
        # filter parameters are added to the API.
        filters = _extract_list_filters(frappe.form_dict)

        service = CandidateService()
        result = service.list_candidates(
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
def search_candidates() -> dict:
    """Search Candidate records across multiple fields.

    Searches across: first_name, last_name, email, phone,
    profession, current_location.

    To add a new searchable field, update ``SEARCHABLE_FIELDS`` in
    ``CandidateService`` — no changes are needed here.

    Query Parameters
    ----------------
    search     : str  (required)
        The search term.  Partial matches are supported.
    page       : int  (default 1)
    page_size  : int  (default 20, max 100)
    status     : str  (optional)
        Narrow search results by status.
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

        service = CandidateService()
        result = service.search_candidates(
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
# Sub-Resource & International Candidate Endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
@employer_required
def get_education(candidate_id: str) -> dict:
    """List all Candidate Education records for a Candidate."""
    try:
        service = CandidateService()
        data = service.get_education(candidate_id=candidate_id)
        return success_response(data=data)
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def update_education(candidate_id: str, **kwargs) -> dict:
    """Update Candidate Education table for a Candidate."""
    try:
        payload = _get_payload()
        education = payload.get("education") or payload.get("data") or kwargs.get("education") or []
        if isinstance(education, str):
            education = frappe.parse_json(education)
        service = CandidateService()
        result = service.update_education(candidate_id=candidate_id, education=education)
        return success_response(data=result, message="Education records updated successfully.")
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_experience(candidate_id: str) -> dict:
    """List all Candidate Experience records for a Candidate."""
    try:
        service = CandidateService()
        data = service.get_experience(candidate_id=candidate_id)
        return success_response(data=data)
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def update_experience(candidate_id: str, **kwargs) -> dict:
    """Update Candidate Experience table for a Candidate."""
    try:
        payload = _get_payload()
        experience = payload.get("experience") or payload.get("data") or kwargs.get("experience") or []
        if isinstance(experience, str):
            experience = frappe.parse_json(experience)
        service = CandidateService()
        result = service.update_experience(candidate_id=candidate_id, experience=experience)
        return success_response(data=result, message="Experience records updated successfully.")
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_skills(candidate_id: str) -> dict:
    """List all Candidate Skill records for a Candidate."""
    try:
        service = CandidateService()
        data = service.get_skills(candidate_id=candidate_id)
        return success_response(data=data)
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def update_skills(candidate_id: str, **kwargs) -> dict:
    """Update Candidate Skill table for a Candidate."""
    try:
        payload = _get_payload()
        skills = payload.get("skills") or payload.get("data") or kwargs.get("skills") or []
        if isinstance(skills, str):
            skills = frappe.parse_json(skills)
        service = CandidateService()
        result = service.update_skills(candidate_id=candidate_id, skills=skills)
        return success_response(data=result, message="Skills updated successfully.")
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_certifications(candidate_id: str) -> dict:
    """List all Candidate Certification records for a Candidate."""
    try:
        service = CandidateService()
        data = service.get_certifications(candidate_id=candidate_id)
        return success_response(data=data)
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def update_certifications(candidate_id: str, **kwargs) -> dict:
    """Update Candidate Certification table for a Candidate."""
    try:
        payload = _get_payload()
        certifications = payload.get("certifications") or payload.get("data") or kwargs.get("certifications") or []
        if isinstance(certifications, str):
            certifications = frappe.parse_json(certifications)
        service = CandidateService()
        result = service.update_certifications(candidate_id=candidate_id, certifications=certifications)
        return success_response(data=result, message="Certifications updated successfully.")
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_languages(candidate_id: str) -> dict:
    """List all Candidate Language records for a Candidate."""
    try:
        service = CandidateService()
        data = service.get_languages(candidate_id=candidate_id)
        return success_response(data=data)
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def update_languages(candidate_id: str, **kwargs) -> dict:
    """Update Candidate Language table for a Candidate."""
    try:
        payload = _get_payload()
        languages = payload.get("languages") or payload.get("data") or kwargs.get("languages") or []
        if isinstance(languages, str):
            languages = frappe.parse_json(languages)
        service = CandidateService()
        result = service.update_languages(candidate_id=candidate_id, languages=languages)
        return success_response(data=result, message="Languages updated successfully.")
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_documents(candidate_id: str) -> dict:
    """List all Candidate Document records for a Candidate."""
    try:
        service = CandidateService()
        data = service.get_documents(candidate_id=candidate_id)
        return success_response(data=data)
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def update_documents(candidate_id: str, **kwargs) -> dict:
    """Update Candidate Document table for a Candidate."""
    try:
        payload = _get_payload()
        documents = payload.get("documents") or payload.get("data") or kwargs.get("documents") or []
        if isinstance(documents, str):
            documents = frappe.parse_json(documents)
        service = CandidateService()
        result = service.update_documents(candidate_id=candidate_id, documents=documents)
        return success_response(data=result, message="Documents updated successfully.")
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def update_passport_and_visa(candidate_id: str, **kwargs) -> dict:
    """Update passport and visa details for a Candidate."""
    try:
        payload = _get_payload()
        if kwargs:
            payload.update(kwargs)
        service = CandidateService()
        result = service.update_passport_and_visa(candidate_id=candidate_id, data=payload)
        return success_response(data=result, message="Passport and visa details updated successfully.")
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def list_international_candidates() -> dict:
    """Return a paginated list of International Candidates."""
    try:
        page = int(frappe.form_dict.get("page", DEFAULT_PAGE))
        page_size = int(frappe.form_dict.get("page_size", DEFAULT_PAGE_SIZE))
        order_by = frappe.form_dict.get("order_by", "creation")
        order_dir = frappe.form_dict.get("order_dir", "desc")

        filters = _extract_list_filters(frappe.form_dict)

        service = CandidateService()
        result = service.list_international_candidates(
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
def list_domestic_candidates() -> dict:
    """Return a paginated list of Domestic Candidates."""
    try:
        page = int(frappe.form_dict.get("page", DEFAULT_PAGE))
        page_size = int(frappe.form_dict.get("page_size", DEFAULT_PAGE_SIZE))
        order_by = frappe.form_dict.get("order_by", "creation")
        order_dir = frappe.form_dict.get("order_dir", "desc")

        filters = _extract_list_filters(frappe.form_dict)

        service = CandidateService()
        result = service.list_domestic_candidates(
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
def get_domestic_candidate(candidate_id: str) -> dict:
    """Retrieve details for a single Domestic Candidate."""
    try:
        service = CandidateService()
        data = service.get_domestic_candidate(candidate_id=candidate_id)
        return success_response(data=data)
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def update_domestic_candidate(candidate_id: str, **kwargs) -> dict:
    """Update profile details for a Domestic Candidate."""
    try:
        payload = _get_payload()
        if kwargs:
            payload.update(kwargs)
        service = CandidateService()
        result = service.update_domestic_candidate(candidate_id=candidate_id, data=payload)
        return success_response(data=result, message="Domestic candidate profile updated successfully.")
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_profile_completeness(candidate_id: str) -> dict:
    """Return profile completeness score for a Candidate."""
    try:
        service = CandidateService()
        data = service.get_profile_completeness(candidate_id=candidate_id)
        return success_response(data=data)
    except ATSException as exc:
        return _handle_ats_exception(exc)


# ---------------------------------------------------------------------------
# Private Input Helpers
# ---------------------------------------------------------------------------


def _extract_candidate_fields(form_dict, exclude: set[str] | None = None) -> dict:
    """Extract Candidate field values from the Frappe form dict.

    Strips ``frappe.form_dict`` keys that are internal Frappe parameters
    (``cmd``, ``csrf_token``, etc.) and any caller-specified ``exclude``
    keys, returning only the fields that belong to the Candidate payload.

    Parameters
    ----------
    form_dict : frappe.local.form_dict
        The raw request parameters dict.
    exclude : set[str] or None, optional
        Additional keys to exclude from the output (e.g. ``{"candidate_id"}``
        when the ID is a path parameter rather than a body field).

    Returns
    -------
    dict
        A clean dict of candidate field key/value pairs.
    """
    # Keys injected by Frappe's request handling — never candidate data.
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

    if form_dict.get("status"):
        filters["status"] = form_dict["status"]
    if form_dict.get("profession"):
        filters["profession"] = form_dict["profession"]
    if form_dict.get("city"):
        filters["city"] = form_dict["city"]
    if form_dict.get("country"):
        filters["country"] = form_dict["country"]
    if form_dict.get("location"):
        filters["location"] = form_dict["location"]
    if form_dict.get("current_location"):
        filters["current_location"] = form_dict["current_location"]

    return filters
