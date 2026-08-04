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
from frappe.exceptions import DuplicateEntryError, LinkExistsError

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
    ATSPermissionError,
    ATSValidationError,
)
from recruitrain_employer.utils.permissions import (
    get_current_company,
    is_company_member,
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
        """Create a new Offer record."""
        self._validator.validate_create(data)

        payload = dict(data)

        if "salary" in payload and "offered_salary" not in payload:
            payload["offered_salary"] = payload["salary"]
        if "start_date" in payload and "joining_date" not in payload:
            payload["joining_date"] = payload["start_date"]
        if "status" in payload and "offer_status" not in payload:
            payload["offer_status"] = payload["status"]

        job_app_id = payload.get("job_application")
        interview_id = payload.get("interview")

        if interview_id and not job_app_id:
            interview_doc = frappe.get_doc(DOCTYPE_INTERVIEW, interview_id)
            job_app_id = interview_doc.job_application
            payload["job_application"] = job_app_id

        if job_app_id:
            app_doc = frappe.get_doc(DOCTYPE_JOB_APPLICATION, job_app_id)
            if not payload.get("candidate"):
                payload["candidate"] = app_doc.candidate
            if not payload.get("job_opening"):
                payload["job_opening"] = app_doc.job_opening
            if not payload.get("company"):
                payload["company"] = app_doc.company

        # Enforce Company Scoping
        self._assert_company_access(payload.get("company"))

        self._assert_no_active_offer(payload.get("job_application"))

        if not payload.get("offer_status"):
            payload["offer_status"] = "Draft"
        if not payload.get("offer_date"):
            payload["offer_date"] = frappe.utils.today()
        if not payload.get("offer_name"):
            payload["offer_name"] = f"OFF-{frappe.generate_hash(length=8)}"

        doc = frappe.new_doc(DOCTYPE_OFFER)
        self._apply_changed_fields(doc, payload)
        try:
            doc.insert(ignore_permissions=True)
        except DuplicateEntryError as exc:
            raise ATSConflictError(
                f"Offer conflict during creation.",
                details={"offer_name": payload.get("offer_name")},
            ) from exc

        self._notify(
            title="New Offer Drafted",
            message=f"Offer {doc.name} was created for candidate {doc.candidate}.",
            priority="High",
            category="Offer",
            company=doc.company,
            entity_id=doc.name,
            action_url=f"/offers/{doc.name}",
            action_label="View Offer",
        )

        return self._serialize_offer(doc, fields=_DETAIL_FIELDS)


    def get_offer(self, offer_id: str) -> dict:
        """Retrieve a single Offer record by ID."""
        if not offer_id:
            raise ATSValidationError("offer_id is required.", field="offer_id")

        doc = self._get_or_raise(offer_id)
        self._assert_company_access(doc.company)
        return self._serialize_offer(doc, fields=_DETAIL_FIELDS)

    def update_offer(self, offer_id: str, data: dict) -> dict:
        """Update mutable fields of an existing Offer record."""
        if not offer_id:
            raise ATSValidationError("offer_id is required.", field="offer_id")

        self._validator.validate_update(data)
        doc = self._get_or_raise(offer_id)
        self._assert_company_access(doc.company)

        payload = dict(data)
        if "salary" in payload and "offered_salary" not in payload:
            payload["offered_salary"] = payload["salary"]
        if "start_date" in payload and "joining_date" not in payload:
            payload["joining_date"] = payload["start_date"]
        if "status" in payload and "offer_status" not in payload:
            payload["offer_status"] = payload["status"]

        changed_fields = self._apply_changed_fields(doc, payload)
        if changed_fields:
            try:
                doc.save(ignore_permissions=True)
            except DuplicateEntryError as exc:
                raise ATSConflictError(
                    f"Offer conflict during update.",
                    details={"offer_id": offer_id},
                ) from exc

        return self._serialize_offer(doc, fields=_DETAIL_FIELDS)

    def delete_offer(self, offer_id: str) -> None:
        """Delete an Offer record safely."""
        if not offer_id:
            raise ATSValidationError("offer_id is required.", field="offer_id")

        doc = self._get_or_raise(offer_id)
        self._assert_company_access(doc.company)

        try:
            frappe.delete_doc(
                DOCTYPE_OFFER,
                offer_id,
                ignore_permissions=True,
                force=False,
            )
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

        escaped_search = search.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        term = f"%{escaped_search}%"
        or_filters = [[field, "like", term] for field in SEARCHABLE_FIELDS]

        # Fix Priority 4: Ensure db.count uses both filters and or_filters
        total = frappe.db.count(DOCTYPE_OFFER, filters=orm_filters, or_filters=or_filters)

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
        self._assert_company_access(doc.company)

        frappe.db.set_value(
            DOCTYPE_OFFER,
            offer_id,
            "offer_status",
            new_status,
            update_modified=True,
        )

        doc.reload()

        self._notify(
            title="Offer Status Updated",
            message=f"Offer {doc.name} status updated to '{new_status}'.",
            priority="High",
            category="Offer",
            company=doc.company,
            entity_id=doc.name,
            action_url=f"/offers/{doc.name}",
            action_label="View Offer",
        )

        return self._serialize_offer(doc, fields=_DETAIL_FIELDS)

    @staticmethod
    def _notify(title: str, message: str, priority: str, category: str, company: str, entity_id: str, action_url: str, action_label: str) -> None:
        try:
            from recruitrain_employer.services.notification_service import NotificationService
            from recruitrain_employer.utils.permissions import get_current_company
            recipient = getattr(frappe.session, "user", "") or "Administrator"
            if recipient == "Guest":
                recipient = "Administrator"
            ns = NotificationService()
            target_company = company or get_current_company()
            ns.create_notification(
                raw_data={
                    "title": title,
                    "message": message,
                    "priority": priority,
                    "category": category,
                    "entity_type": "Offer",
                    "entity_id": entity_id,
                    "action_url": action_url,
                    "action_label": action_label,
                },
                company=target_company,
                recipient=recipient,
                created_by=getattr(frappe.session, "user", "System"),
            )
        except Exception as exc:
            frappe.logger().error(f"Offer notification error: {exc}")


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

    @staticmethod
    def _assert_company_access(company: str | None) -> None:
        """Assert user has permission to access records of company."""
        if not company:
            return
        if getattr(frappe.session, "user", "") == "Administrator":
            return
        current_comp = get_current_company()
        if company != current_comp:
            raise ATSPermissionError(
                f"Cross-company access prohibited. Record belongs to '{company}', active user belongs to '{current_comp}'.",
                details={"record_company": company, "user_company": current_comp},
            )

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
        meta = frappe.get_meta(doc.doctype)
        for field, new_value in data.items():
            if not meta.has_field(field):
                continue
            current_value = doc.get(field)
            if current_value != new_value:
                setattr(doc, field, new_value)
                changed[field] = new_value
        return changed

    def _build_filters(self, filters: dict) -> dict:
        """Construct ORM filters for Offer queries with company scoping."""
        orm: dict = {}

        # Priority 2: Automatic Company Scoping
        if getattr(frappe.session, "user", "") != "Administrator":
            orm["company"] = get_current_company()
        elif filters.get("company"):
            orm["company"] = filters["company"]

        if filters.get("job_application"):
            orm["job_application"] = filters["job_application"]

        if filters.get("candidate"):
            orm["candidate"] = filters["candidate"]

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
