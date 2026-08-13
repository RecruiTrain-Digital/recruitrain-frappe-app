# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api.offers
==================================

Offer Management API Endpoints.

Provides REST endpoints for Offer DocType operations including creation,
retrieval, update, deletion, listing, search, and status changes.
"""

from __future__ import annotations

import frappe

from recruitrain_employer.services.offer_service import OfferService
from recruitrain_employer.utils.constants import DEFAULT_PAGE, DEFAULT_PAGE_SIZE
from recruitrain_employer.utils.exceptions import ATSException
from recruitrain_employer.utils.permissions import employer_required
from recruitrain_employer.utils.response import (
    error_response,
    paginated_response,
    success_response,
)


def _handle_ats_exception(exc: Exception) -> dict:
    """Translate an ATSException or Frappe Exception into a standardised error response dict."""
    if isinstance(exc, (frappe.exceptions.DuplicateEntryError, frappe.exceptions.TimestampMismatchError)):
        msg = "This record has been modified by another user. Please reload and try again." if isinstance(exc, frappe.exceptions.TimestampMismatchError) else str(exc)
        return error_response(
            code="CONFLICT",
            message=msg,
            http_status_code=409,
        )
    if isinstance(exc, ATSException):
        return error_response(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            http_status_code=400 if exc.code == "VALIDATION_ERROR" else 404 if exc.code == "NOT_FOUND" else 403 if exc.code == "PERMISSION_DENIED" else 409 if exc.code == "CONFLICT" else 400,
        )
    return error_response(
        code="INTERNAL_SERVER_ERROR",
        message="An error occurred while processing offer request.",
        details={"error": str(exc)},
        http_status_code=500,
    )


# ---------------------------------------------------------------------------
# Offer CRUD Endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
@employer_required
def create_offer() -> dict:
    """Create a new Offer record for a Job Application / Interview."""
    try:
        data = _extract_offer_fields(frappe.form_dict)
        service = OfferService()
        offer = service.create_offer(data)
        return success_response(
            data=offer,
            message="Offer created successfully.",
        )
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_offer(offer_id: str | None = None) -> dict:
    """Retrieve a single Offer record by ID."""
    try:
        target_id = offer_id or frappe.form_dict.get("offer_id") or frappe.form_dict.get("name")
        service = OfferService()
        offer = service.get_offer(offer_id=target_id)
        return success_response(data=offer)
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def update_offer(offer_id: str | None = None) -> dict:
    """Update an existing Offer record."""
    try:
        target_id = offer_id or frappe.form_dict.get("offer_id") or frappe.form_dict.get("name")
        data = _extract_offer_fields(
            frappe.form_dict, exclude={"offer_id", "name"}
        )
        service = OfferService()
        offer = service.update_offer(offer_id=target_id, data=data)
        return success_response(
            data=offer,
            message="Offer updated successfully.",
        )
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def delete_offer(offer_id: str | None = None) -> dict:
    """Delete an Offer record."""
    try:
        target_id = offer_id or frappe.form_dict.get("offer_id") or frappe.form_dict.get("name")
        service = OfferService()
        service.delete_offer(offer_id=target_id)
        return success_response(
            message=f"Offer '{target_id}' was deleted successfully."
        )
    except ATSException as exc:
        return _handle_ats_exception(exc)


# ---------------------------------------------------------------------------
# Status Management Endpoint
# ---------------------------------------------------------------------------


@frappe.whitelist()
@employer_required
def change_status(offer_id: str | None = None, new_status: str | None = None) -> dict:
    """Change the status of an Offer."""
    try:
        target_id = offer_id or frappe.form_dict.get("offer_id") or frappe.form_dict.get("name")
        status_val = new_status or frappe.form_dict.get("new_status") or frappe.form_dict.get("offer_status") or frappe.form_dict.get("status")

        service = OfferService()
        offer = service.change_status(
            offer_id=target_id,
            new_status=status_val,
        )
        return success_response(
            data=offer,
            message=f"Offer status updated to '{status_val}'.",
        )
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def send_offer(offer_id: str | None = None) -> dict:
    """Send an Offer to candidate."""
    target_id = offer_id or frappe.form_dict.get("offer_id") or frappe.form_dict.get("name")
    return change_status(offer_id=target_id, new_status="Sent")


@frappe.whitelist()
@employer_required
def accept_offer(offer_id: str | None = None) -> dict:
    """Accept an Offer."""
    target_id = offer_id or frappe.form_dict.get("offer_id") or frappe.form_dict.get("name")
    return change_status(offer_id=target_id, new_status="Accepted")


@frappe.whitelist()
@employer_required
def reject_offer(offer_id: str | None = None) -> dict:
    """Reject an Offer."""
    target_id = offer_id or frappe.form_dict.get("offer_id") or frappe.form_dict.get("name")
    return change_status(offer_id=target_id, new_status="Rejected")


@frappe.whitelist()
@employer_required
def withdraw_offer(offer_id: str | None = None) -> dict:
    """Withdraw an Offer."""
    target_id = offer_id or frappe.form_dict.get("offer_id") or frappe.form_dict.get("name")
    return change_status(offer_id=target_id, new_status="Withdrawn")



# ---------------------------------------------------------------------------
# List & Search Endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
@employer_required
def list_offers() -> dict:
    """Return a paginated list of Offer records."""
    try:
        page = int(frappe.form_dict.get("page", DEFAULT_PAGE))
        page_size = int(frappe.form_dict.get("page_size", DEFAULT_PAGE_SIZE))
        order_by = frappe.form_dict.get("order_by", "creation")
        order_dir = frappe.form_dict.get("order_dir", "desc")

        filters = _extract_list_filters(frappe.form_dict)

        service = OfferService()
        result = service.list_offers(
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
def search_offers() -> dict:
    """Search Offer records across candidate, company, job_opening, offer_name, offer_status, joining_date."""
    try:
        search = frappe.form_dict.get("search", "").strip()
        page = int(frappe.form_dict.get("page", DEFAULT_PAGE))
        page_size = int(frappe.form_dict.get("page_size", DEFAULT_PAGE_SIZE))
        order_by = frappe.form_dict.get("order_by", "creation")
        order_dir = frappe.form_dict.get("order_dir", "desc")

        filters = _extract_list_filters(frappe.form_dict)

        service = OfferService()
        result = service.search_offers(
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


def _extract_offer_fields(
    form_dict, exclude: set[str] | None = None
) -> dict:
    """Extract offer fields from frappe.form_dict."""
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
        "offer_status",
        "status",
        "joining_date",
        "offer_date",
    ):
        if form_dict.get(key):
            filters[key] = form_dict[key]

    return filters
