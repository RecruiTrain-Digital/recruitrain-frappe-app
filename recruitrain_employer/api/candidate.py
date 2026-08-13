# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api.candidate
====================================

Thin Controller API Endpoints for Candidate Subsystem.
Enforces authentication, RBAC, company scoping, and standard response envelopes.
"""

from __future__ import annotations

from typing import Any
import frappe

import traceback
from frappe.exceptions import (
    DoesNotExistError as FrappeDoesNotExistError,
    DuplicateEntryError as FrappeDuplicateEntryError,
    LinkValidationError as FrappeLinkValidationError,
    PermissionError as FrappePermissionError,
    ValidationError as FrappeValidationError,
)

from recruitrain_employer.services.candidate_service import CandidateService
from recruitrain_employer.utils.constants import DEFAULT_PAGE, DEFAULT_PAGE_SIZE
from recruitrain_employer.utils.exceptions import (
    ATSCompanyNotFoundError,
    ATSConflictError,
    ATSException,
    ATSNotFoundError,
    ATSPermissionError,
    ATSValidationError,
)
from recruitrain_employer.utils.permissions import employer_required
from recruitrain_employer.utils.response import (
    error_response,
    paginated_response,
    success_response,
)


def _handle_ats_exception(exc: Exception) -> dict[str, Any]:
    """Translate an ATSException, Frappe exception, or unexpected error into standard error envelope."""
    # Diagnostic logging of exception stack
    tb_str = traceback.format_exc()
    frappe.logger().error(
        f"[CandidateAPI] Exception caught: {type(exc).__name__}: {exc}\nTraceback:\n{tb_str}"
    )

    # 1. Permission / Authorization Errors -> HTTP 403
    if isinstance(exc, (ATSPermissionError, FrappePermissionError)):
        msg = getattr(exc, "message", None) or str(exc)
        details = getattr(exc, "details", None) or {"error": str(exc)}
        return error_response(
            code="PERMISSION_DENIED",
            message=msg,
            details=details,
            http_status_code=403,
        )

    # 2. Company Not Found -> HTTP 404
    if isinstance(exc, ATSCompanyNotFoundError):
        return error_response(
            code="COMPANY_NOT_FOUND",
            message=exc.message,
            details=exc.details,
            http_status_code=404,
        )

    # 3. Not Found Errors -> HTTP 404
    if isinstance(exc, (ATSNotFoundError, FrappeDoesNotExistError)):
        msg = getattr(exc, "message", None) or str(exc)
        details = getattr(exc, "details", None) or {"error": str(exc)}
        return error_response(
            code="NOT_FOUND",
            message=msg,
            details=details,
            http_status_code=404,
        )

    # 4. Conflict Errors / Concurrent Edits -> HTTP 409
    if isinstance(exc, (ATSConflictError, FrappeDuplicateEntryError, frappe.exceptions.TimestampMismatchError)):
        msg = getattr(exc, "message", None) or str(exc)
        if isinstance(exc, frappe.exceptions.TimestampMismatchError):
            msg = "This record has been modified by another user. Please reload and try again."
        details = getattr(exc, "details", None) or {"error": str(exc)}
        return error_response(
            code="CONFLICT",
            message=msg,
            details=details,
            http_status_code=409,
        )

    # 5. Validation Errors -> HTTP 400
    if isinstance(exc, (ATSValidationError, FrappeValidationError, FrappeLinkValidationError)):
        msg = getattr(exc, "message", None) or str(exc)
        details = getattr(exc, "details", None) or {"error": str(exc)}
        return error_response(
            code="VALIDATION_ERROR",
            message=msg,
            details=details,
            http_status_code=400,
        )

    # 6. Generic ATSException -> HTTP 400 or custom status
    if isinstance(exc, ATSException):
        status_code = getattr(exc, "http_status_code", 400)
        return error_response(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            http_status_code=status_code,
        )

    # 7. Unexpected System Error -> HTTP 500
    return error_response(
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected error occurred while processing candidate request.",
        details={"error": str(exc)},
        http_status_code=500,
    )


def _get_payload() -> dict[str, Any]:
    """Safely extract payload from request JSON or form_dict."""
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
        d = dict(form)
        d.pop("cmd", None)
        return d
    return {}


# ---------------------------------------------------------------------------
# Candidate CRUD Endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
@employer_required
def create_candidate() -> dict[str, Any]:
    """Create a candidate record."""
    try:
        payload = _get_payload()
        service = CandidateService()
        result = service.create_candidate(payload)
        return success_response(data=result, message="Candidate profile created successfully.")
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_candidate(candidate_id: str | None = None) -> dict[str, Any]:
    """Retrieve full candidate profile."""
    try:
        if not candidate_id:
            payload = _get_payload()
            candidate_id = payload.get("candidate_id") or payload.get("name")
        service = CandidateService()
        result = service.get_candidate(candidate_id)
        return success_response(data=result)
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def update_candidate(candidate_id: str | None = None) -> dict[str, Any]:
    """Update candidate profile fields."""
    try:
        payload = _get_payload()
        if not candidate_id:
            candidate_id = payload.pop("candidate_id", None) or payload.pop("name", None)
        service = CandidateService()
        result = service.update_candidate(candidate_id, payload)
        return success_response(data=result, message="Candidate profile updated successfully.")
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def delete_candidate(candidate_id: str | None = None) -> dict[str, Any]:
    """Delete candidate record."""
    try:
        if not candidate_id:
            payload = _get_payload()
            candidate_id = payload.get("candidate_id") or payload.get("name")
        service = CandidateService()
        result = service.delete_candidate(candidate_id)
        return success_response(data=result, message="Candidate record deleted successfully.")
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def list_candidates() -> dict[str, Any]:
    """List company-scoped candidates with pagination and filters."""
    try:
        payload = _get_payload()
        page = payload.get("page", DEFAULT_PAGE)
        page_size = payload.get("page_size", DEFAULT_PAGE_SIZE)
        order_by = payload.get("order_by", "creation desc")
        status = payload.get("status")
        profession = payload.get("profession")
        employment_type = payload.get("employment_type")
        country = payload.get("country")
        search_term = payload.get("search") or payload.get("search_term")

        service = CandidateService()
        result = service.list_candidates(
            page=page,
            page_size=page_size,
            order_by=order_by,
            status=status,
            profession=profession,
            employment_type=employment_type,
            country=country,
            search_term=search_term,
        )
        return paginated_response(
            items=result["items"],
            total=result["total"],
            page=result["page"],
            page_size=result["page_size"],
            total_pages=result["total_pages"],
            message="Candidates retrieved successfully.",
        )
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def search_candidates() -> dict[str, Any]:
    """Search candidate profiles by term."""
    try:
        payload = _get_payload()
        query = payload.get("query") or payload.get("search_term") or payload.get("search")
        page = payload.get("page", DEFAULT_PAGE)
        page_size = payload.get("page_size", DEFAULT_PAGE_SIZE)

        service = CandidateService()
        result = service.list_candidates(
            page=page,
            page_size=page_size,
            search_term=query,
        )
        return paginated_response(
            items=result["items"],
            total=result["total"],
            page=result["page"],
            page_size=result["page_size"],
            total_pages=result["total_pages"],
            message="Search results retrieved successfully.",
        )
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def list_domestic_candidates() -> dict[str, Any]:
    """List domestic candidates."""
    try:
        payload = _get_payload()
        page = payload.get("page", DEFAULT_PAGE)
        page_size = payload.get("page_size", DEFAULT_PAGE_SIZE)
        order_by = payload.get("order_by", "creation desc")

        service = CandidateService()
        result = service.list_domestic_candidates(page=page, page_size=page_size, order_by=order_by)
        return paginated_response(
            items=result["items"],
            total=result["total"],
            page=result["page"],
            page_size=result["page_size"],
            total_pages=result["total_pages"],
            message="Domestic candidates retrieved successfully.",
        )
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def list_international_candidates() -> dict[str, Any]:
    """List international candidates."""
    try:
        payload = _get_payload()
        page = payload.get("page", DEFAULT_PAGE)
        page_size = payload.get("page_size", DEFAULT_PAGE_SIZE)
        order_by = payload.get("order_by", "creation desc")

        service = CandidateService()
        result = service.list_international_candidates(page=page, page_size=page_size, order_by=order_by)
        return paginated_response(
            items=result["items"],
            total=result["total"],
            page=result["page"],
            page_size=result["page_size"],
            total_pages=result["total_pages"],
            message="International candidates retrieved successfully.",
        )
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_profile_completeness(candidate_id: str | None = None) -> dict[str, Any]:
    """Calculate and return profile completeness percentage."""
    try:
        if not candidate_id:
            payload = _get_payload()
            candidate_id = payload.get("candidate_id") or payload.get("name")
        service = CandidateService()
        result = service.get_profile_completeness(candidate_id)
        return success_response(data=result)
    except Exception as exc:
        return _handle_ats_exception(exc)


# ---------------------------------------------------------------------------
# Sub-Resource Endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
@employer_required
def get_education(candidate_id: str | None = None) -> dict[str, Any]:
    try:
        if not candidate_id:
            payload = _get_payload()
            candidate_id = payload.get("candidate_id") or payload.get("name")
        service = CandidateService()
        candidate = service.get_candidate(candidate_id)
        return success_response(data=candidate.get("education", []))
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def update_education(candidate_id: str | None = None) -> dict[str, Any]:
    try:
        payload = _get_payload()
        if not candidate_id:
            candidate_id = payload.pop("candidate_id", None) or payload.pop("name", None)
        education = payload.get("education") or payload.get("items") or []
        service = CandidateService()
        result = service.update_subresource(candidate_id, "education", education)
        return success_response(data=result.get("education", []), message="Education updated successfully.")
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_experience(candidate_id: str | None = None) -> dict[str, Any]:
    try:
        if not candidate_id:
            payload = _get_payload()
            candidate_id = payload.get("candidate_id") or payload.get("name")
        service = CandidateService()
        candidate = service.get_candidate(candidate_id)
        return success_response(data=candidate.get("experience", []))
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def update_experience(candidate_id: str | None = None) -> dict[str, Any]:
    try:
        payload = _get_payload()
        if not candidate_id:
            candidate_id = payload.pop("candidate_id", None) or payload.pop("name", None)
        experience = payload.get("experience") or payload.get("items") or []
        service = CandidateService()
        result = service.update_subresource(candidate_id, "experience", experience)
        return success_response(data=result.get("experience", []), message="Experience updated successfully.")
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_skills(candidate_id: str | None = None) -> dict[str, Any]:
    try:
        if not candidate_id:
            payload = _get_payload()
            candidate_id = payload.get("candidate_id") or payload.get("name")
        service = CandidateService()
        candidate = service.get_candidate(candidate_id)
        return success_response(data=candidate.get("skills", []))
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def update_skills(candidate_id: str | None = None) -> dict[str, Any]:
    try:
        payload = _get_payload()
        if not candidate_id:
            candidate_id = payload.pop("candidate_id", None) or payload.pop("name", None)
        skills = payload.get("skills") or payload.get("items") or []
        service = CandidateService()
        result = service.update_subresource(candidate_id, "skills", skills)
        return success_response(data=result.get("skills", []), message="Skills updated successfully.")
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_certifications(candidate_id: str | None = None) -> dict[str, Any]:
    try:
        if not candidate_id:
            payload = _get_payload()
            candidate_id = payload.get("candidate_id") or payload.get("name")
        service = CandidateService()
        candidate = service.get_candidate(candidate_id)
        return success_response(data=candidate.get("certifications", []))
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def update_certifications(candidate_id: str | None = None) -> dict[str, Any]:
    try:
        payload = _get_payload()
        if not candidate_id:
            candidate_id = payload.pop("candidate_id", None) or payload.pop("name", None)
        certifications = payload.get("certifications") or payload.get("items") or []
        service = CandidateService()
        result = service.update_subresource(candidate_id, "certifications", certifications)
        return success_response(data=result.get("certifications", []), message="Certifications updated successfully.")
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_languages(candidate_id: str | None = None) -> dict[str, Any]:
    try:
        if not candidate_id:
            payload = _get_payload()
            candidate_id = payload.get("candidate_id") or payload.get("name")
        service = CandidateService()
        candidate = service.get_candidate(candidate_id)
        return success_response(data=candidate.get("languages", []))
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def update_languages(candidate_id: str | None = None) -> dict[str, Any]:
    try:
        payload = _get_payload()
        if not candidate_id:
            candidate_id = payload.pop("candidate_id", None) or payload.pop("name", None)
        languages = payload.get("languages") or payload.get("items") or []
        service = CandidateService()
        result = service.update_subresource(candidate_id, "languages", languages)
        return success_response(data=result.get("languages", []), message="Languages updated successfully.")
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_documents(candidate_id: str | None = None) -> dict[str, Any]:
    try:
        if not candidate_id:
            payload = _get_payload()
            candidate_id = payload.get("candidate_id") or payload.get("name")
        service = CandidateService()
        candidate = service.get_candidate(candidate_id)
        return success_response(data=candidate.get("documents", []))
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def update_documents(candidate_id: str | None = None) -> dict[str, Any]:
    try:
        payload = _get_payload()
        if not candidate_id:
            candidate_id = payload.pop("candidate_id", None) or payload.pop("name", None)
        documents = payload.get("documents") or payload.get("items") or []
        service = CandidateService()
        result = service.update_subresource(candidate_id, "documents", documents)
        return success_response(data=result.get("documents", []), message="Documents updated successfully.")
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def update_passport_and_visa(candidate_id: str | None = None) -> dict[str, Any]:
    try:
        payload = _get_payload()
        if not candidate_id:
            candidate_id = payload.pop("candidate_id", None) or payload.pop("name", None)
        service = CandidateService()
        result = service.update_candidate(candidate_id, payload)
        return success_response(data=result, message="Passport and Visa info updated successfully.")
    except Exception as exc:
        return _handle_ats_exception(exc)
