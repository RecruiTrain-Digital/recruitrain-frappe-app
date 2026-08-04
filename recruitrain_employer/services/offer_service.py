# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.services.offer_service
=============================================

Offer Management Business Logic Service.

Owns all business logic related to:
- Offer creation, updates, retrieval, and safe deletion
- Auto-derivation of Candidate, Company, Job Opening from linked Job Application / Interview
- Active offer duplicate prevention
- Offer search and paginated listing
- Offer status management (Draft, Sent, Accepted, Rejected, Withdrawn, Expired)

All public methods on ``OfferService`` are called from the API layer.
"""

from __future__ import annotations

import frappe
from frappe.exceptions import LinkExistsError

from recruitrain_employer.utils.constants import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    DOCTYPE_INTERVIEW,
    DOCTYPE_JOB_APPLICATION,
    DOCTYPE_OFFER,
    MAX_PAGE_SIZE,
)
from recruitrain_employer.utils.exceptions import (
    ATSConflictError,
    ATSNotFoundError,
    ATSValidationError,
)
from recruitrain_employer.validators.offer_validator import (
    ALLOWED_OFFER_STATUSES,
    OfferValidator,
)

SEARCHABLE_FIELDS: tuple[str, ...] = (
    "candidate",
    "company",
    "job_opening",
    "name",
    "offer_name",
    "offer_status",
    "joining_date",
)

ALLOWED_SORT_FIELDS: frozenset[str] = frozenset(
    [
        "creation",
        "modified",
        "offer_date",
        "joining_date",
        "candidate",
        "company",
        "job_opening",
        "offer_status",
        "offered_salary",
    ]
)

_FRAPPE_METADATA_FIELDS: frozenset[str] = frozenset(
    [
        "owner",
        "modified_by",
        "creation",
        "modified",
        "idx",
        "docstatus",
        "doctype",
        "parent",
        "parentfield",
        "parenttype",
    ]
)

_LIST_FIELDS: list[str] = [
    "name",
    "offer_name",
    "candidate",
    "job_application",
    "job_opening",
    "company",
    "offered_salary",
    "currency",
    "joining_date",
    "offer_date",
    "expiry_date",
    "employment_type",
    "offer_status",
]

_DETAIL_FIELDS: list[str] = _LIST_FIELDS + [
    "probation_period_months",
    "reporting_manager",
    "response_date",
    "candidate_remarks",
    "offer_letter",
    "notes",
]


class OfferService:
    """Encapsulates business logic for Offer management."""

    def __init__(self) -> None:
        self._validator = OfferValidator()

    def create_offer(self, data: dict) -> dict:
        """Create a new Offer record.

        Determines candidate, company, and job_opening from the linked Interview or Job Application.
        Prevents duplicate active offers for the same Job Application / Interview.
        """
        self._validator.validate_create(data)

        payload = dict(data)

        # Normalize field aliases
        if "salary" in payload and "offered_salary" not in payload:
            payload["offered_salary"] = payload["salary"]
        if "start_date" in payload and "joining_date" not in payload:
            payload["joining_date"] = payload["start_date"]
        if "status" in payload and "offer_status" not in payload:
            payload["offer_status"] = payload["status"]

        # 1. Derive Job Application from Interview if provided
        job_app_id = payload.get("job_application")
        interview_id = payload.get("interview")

        if interview_id and not job_app_id:
            interview_doc = frappe.get_doc(DOCTYPE_INTERVIEW, interview_id)
            job_app_id = interview_doc.job_application
            payload["job_application"] = job_app_id

        # 2. Derive Candidate, Company, Job Opening from Job Application
        if job_app_id:
            app_doc = frappe.get_doc(DOCTYPE_JOB_APPLICATION, job_app_id)
            if not payload.get("candidate"):
                payload["candidate"] = app_doc.candidate
            if not payload.get("job_opening"):
                payload["job_opening"] = app_doc.job_opening
            if not payload.get("company"):
                payload["company"] = app_doc.company

        # 3. Check for active duplicate offer
        self._assert_no_active_offer(payload.get("job_application"))

        # Default values
        if not payload.get("offer_status"):
            payload["offer_status"] = "Draft"
        if not payload.get("offer_date"):
            payload["offer_date"] = frappe.utils.today()
        if not payload.get("offer_name"):
            payload["offer_name"] = f"OFF-{frappe.generate_hash(length=8)}"

        doc = frappe.new_doc(DOCTYPE_OFFER)
        self._apply_changed_fields(doc, payload)
        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        # TODO: Log offer creation to Activity Log via ActivityLogService.

        return self._serialize_offer(doc, fields=_DETAIL_FIELDS)

    def get_offer(self, offer_id: str) -> dict:
        """Retrieve a single Offer record by ID."""
        if not offer_id:
            raise ATSValidationError("offer_id is required.", field="offer_id")

        doc = self._get_or_raise(offer_id)
        return self._serialize_offer(doc, fields=_DETAIL_FIELDS)

    def update_offer(self, offer_id: str, data: dict) -> dict:
        """Update mutable fields of an existing Offer record.

        Uses changed-field tracking and skips doc.save() if nothing changed.
        """
        if not offer_id:
            raise ATSValidationError("offer_id is required.", field="offer_id")

        self._validator.validate_update(data)
        doc = self._get_or_raise(offer_id)

        payload = dict(data)
        if "salary" in payload and "offered_salary" not in payload:
            payload["offered_salary"] = payload["salary"]
        if "start_date" in payload and "joining_date" not in payload:
            payload["joining_date"] = payload["start_date"]
        if "status" in payload and "offer_status" not in payload:
            payload["offer_status"] = payload["status"]

        changed_fields = self._apply_changed_fields(doc, payload)
        if changed_fields:
            doc.save(ignore_permissions=True)
            frappe.db.commit()
            # TODO: Log changed_fields to Activity Log via ActivityLogService.

        return self._serialize_offer(doc, fields=_DETAIL_FIELDS)

    def delete_offer(self, offer_id: str) -> None:
        """Delete an Offer record safely."""
        if not offer_id:
            raise ATSValidationError("offer_id is required.", field="offer_id")

        self._get_or_raise(offer_id)

        try:
            frappe.delete_doc(
                DOCTYPE_OFFER,
                offer_id,
                ignore_permissions=True,
                force=False,
            )
            frappe.db.commit()
            # TODO: Replace hard delete with archive workflow in Offer Lifecycle sprint.
        except LinkExistsError as exc:
            raise ATSConflictError(
                f"Offer '{offer_id}' cannot be deleted because it is referenced by linked records.",
                details={"offer_id": offer_id},
            ) from exc

    def list_offers(
        self,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
        filters: dict | None = None,
        order_by: str = "creation",
        order_dir: str = "desc",
    ) -> dict:
        """Return a paginated list of Offer records."""
        page, page_size = self._sanitise_pagination(page, page_size)
        order_clause = self._sanitise_order_by(order_by, order_dir)
        orm_filters = self._build_filters(filters or {})

        total = frappe.db.count(DOCTYPE_OFFER, filters=orm_filters)

        records = frappe.get_list(
            DOCTYPE_OFFER,
            filters=orm_filters,
            fields=_LIST_FIELDS,
            order_by=order_clause,
            limit_start=(page - 1) * page_size,
            limit_page_length=page_size,
            ignore_permissions=True,
        )

        return {
            "data": [dict(r) for r in records],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def search_offers(
        self,
        search: str,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
        filters: dict | None = None,
        order_by: str = "creation",
        order_dir: str = "desc",
    ) -> dict:
        """Search Offers across Candidate, Company, Job Opening, Offer Number, Status, Joining Date."""
        if not search or not search.strip():
            raise ATSValidationError("Search term is required.", field="search")

        page, page_size = self._sanitise_pagination(page, page_size)
        order_clause = self._sanitise_order_by(order_by, order_dir)
        orm_filters = self._build_filters(filters or {})

        term = f"%{search.strip().lower()}%"
        or_filters = [[field, "like", term] for field in SEARCHABLE_FIELDS]

        total = frappe.db.count(DOCTYPE_OFFER, filters=orm_filters)

        records = frappe.get_list(
            DOCTYPE_OFFER,
            filters=orm_filters,
            or_filters=or_filters,
            fields=_LIST_FIELDS,
            order_by=order_clause,
            limit_start=(page - 1) * page_size,
            limit_page_length=page_size,
            ignore_permissions=True,
        )

        return {
            "data": [dict(r) for r in records],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def change_status(self, offer_id: str, new_status: str) -> dict:
        """Change the status of an Offer atomically."""
        if not offer_id:
            raise ATSValidationError("offer_id is required.", field="offer_id")

        if not new_status:
            raise ATSValidationError("new_status is required.", field="new_status")

        self._validator.validate_status(new_status)
        doc = self._get_or_raise(offer_id)

        frappe.db.set_value(
            DOCTYPE_OFFER,
            offer_id,
            "offer_status",
            new_status,
            update_modified=True,
        )
        frappe.db.commit()

        # TODO: Log status change to Activity Log via ActivityLogService.

        doc.reload()
        return self._serialize_offer(doc, fields=_DETAIL_FIELDS)

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _get_or_raise(self, offer_id: str):
        """Fetch an Offer document or raise ATSNotFoundError."""
        if not frappe.db.exists(DOCTYPE_OFFER, offer_id):
            raise ATSNotFoundError(
                f"Offer '{offer_id}' was not found.",
                doctype=DOCTYPE_OFFER,
                name=offer_id,
            )
        return frappe.get_doc(DOCTYPE_OFFER, offer_id)

    def _assert_no_active_offer(self, job_application_id: str | None) -> None:
        """Raise ATSConflictError if an active offer (Draft, Sent, Accepted) exists."""
        if not job_application_id:
            return

        active_statuses = ["Draft", "Sent", "Accepted"]
        existing = frappe.get_all(
            DOCTYPE_OFFER,
            filters={
                "job_application": job_application_id,
                "offer_status": ["in", active_statuses],
            },
            fields=["name", "offer_status"],
            limit=1,
        )
        if existing:
            raise ATSConflictError(
                f"An active offer ('{existing[0]['name']}' with status '{existing[0]['offer_status']}') "
                f"already exists for Job Application '{job_application_id}'. "
                "Multiple active offers are not permitted.",
                details={
                    "job_application": job_application_id,
                    "existing_offer": existing[0]["name"],
                    "status": existing[0]["offer_status"],
                },
            )

    @staticmethod
    def _serialize_offer(doc, fields: list[str]) -> dict:
        """Serialise an Offer document to a clean dict excluding Frappe metadata."""
        return {
            field: doc.get(field)
            for field in fields
            if field not in _FRAPPE_METADATA_FIELDS
        }

    @staticmethod
    def _apply_changed_fields(doc, data: dict) -> dict:
        """Apply changed fields to doc."""
        changed: dict = {}
        for field, new_value in data.items():
            if not hasattr(doc, field):
                continue
            current_value = doc.get(field)
            if current_value != new_value:
                setattr(doc, field, new_value)
                changed[field] = new_value
        return changed

    @staticmethod
    def _build_filters(filters: dict) -> dict:
        """Construct ORM filters for Offer queries."""
        orm: dict = {}

        if filters.get("job_application"):
            orm["job_application"] = filters["job_application"]

        if filters.get("candidate"):
            orm["candidate"] = filters["candidate"]

        if filters.get("company"):
            orm["company"] = filters["company"]

        if filters.get("job_opening"):
            orm["job_opening"] = filters["job_opening"]

        if filters.get("offer_status"):
            orm["offer_status"] = filters["offer_status"]
        elif filters.get("status"):
            orm["offer_status"] = filters["status"]

        if filters.get("joining_date"):
            orm["joining_date"] = filters["joining_date"]

        if filters.get("offer_date"):
            orm["offer_date"] = filters["offer_date"]

        return orm

    @staticmethod
    def _sanitise_pagination(page: int, page_size: int) -> tuple[int, int]:
        """Clamp page and page_size."""
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
        return page, page_size

    @staticmethod
    def _sanitise_order_by(order_by: str, order_dir: str) -> str:
        """Return validated ORDER BY clause."""
        sort_field = order_by if order_by in ALLOWED_SORT_FIELDS else "creation"
        direction = "asc" if str(order_dir).lower() == "asc" else "desc"
        return f"{sort_field} {direction}"
