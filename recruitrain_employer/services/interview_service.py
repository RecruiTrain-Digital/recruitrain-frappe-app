# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.services.interview_service
=================================================

Interview Scheduling Business Logic Service.

Owns all business logic related to:
- Interview creation, updates, and deletion
- Interview search and paginated listing
- Interview status transitions (Scheduled, Rescheduled, Completed, Cancelled, No Show)

All public methods on ``InterviewService`` are called from the
API layer (``recruitrain_employer.api.interviews``).
"""

from __future__ import annotations

import frappe
from frappe.exceptions import DuplicateEntryError, LinkExistsError

from recruitrain_employer.utils.constants import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    DOCTYPE_INTERVIEW,
    DOCTYPE_JOB_APPLICATION,
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
from recruitrain_employer.utils.activity_logger import log_activity
from recruitrain_employer.validators.interview_validator import (
    ALLOWED_INTERVIEW_STATUSES,
    InterviewValidator,
)

SEARCHABLE_FIELDS: tuple[str, ...] = (
    "candidate",
    "company",
    "job_opening",
    "interviewer",
    "scheduled_on",
    "status",
    "name",
    "interview_name",
    "interview_type",
)

ALLOWED_SORT_FIELDS: frozenset[str] = frozenset(
    [
        "creation",
        "modified",
        "scheduled_on",
        "candidate",
        "company",
        "job_opening",
        "interviewer",
        "status",
        "interview_type",
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
    "interview_name",
    "job_application",
    "candidate",
    "job_opening",
    "company",
    "interview_type",
    "scheduled_on",
    "duration",
    "location",
    "interviewer",
    "recruiter",
    "result",
    "status",
]

_DETAIL_FIELDS: list[str] = _LIST_FIELDS + [
    "meeting_link",
    "remarks",
]


class InterviewService:
    """Encapsulates business logic for Interview management."""

    def __init__(self) -> None:
        self._validator = InterviewValidator()

    def create_interview(self, data: dict) -> dict:
        """Create a new Interview record."""
        if not data or not isinstance(data, dict):
            raise ATSValidationError("Input data must be a dictionary.", field="data")

        if not data.get("job_application"):
            raise ATSValidationError("job_application is required.", field="job_application")

        # Derive parent fields from Job Application and enforce referential consistency
        app_doc = frappe.get_doc(DOCTYPE_JOB_APPLICATION, data["job_application"])
        
        # Enforce Company Scoping against Job Application's company
        self._assert_company_access(app_doc.company)

        # Enforce Application Eligibility (Terminal stages: Hired, Rejected, Withdrawn are ineligible)
        app_stage = getattr(app_doc, "current_stage", None) or getattr(app_doc, "status", None)
        if app_stage in ("Hired", "Rejected", "Withdrawn"):
            raise ATSValidationError(
                f"Job Application '{data['job_application']}' is in terminal stage '{app_stage}' and is not eligible for interview scheduling.",
                field="job_application",
                details={"job_application": data["job_application"], "current_stage": app_stage},
            )

        # Validate candidate consistency if explicitly provided
        if data.get("candidate") and str(data["candidate"]) != str(app_doc.candidate):
            raise ATSValidationError(
                f"Candidate '{data['candidate']}' does not match Job Application candidate '{app_doc.candidate}'.",
                field="candidate",
                details={"provided_candidate": data["candidate"], "app_candidate": app_doc.candidate},
            )

        # Validate job_opening consistency if explicitly provided
        if data.get("job_opening") and str(data["job_opening"]) != str(app_doc.job_opening):
            raise ATSValidationError(
                f"Job Opening '{data['job_opening']}' does not match Job Application job opening '{app_doc.job_opening}'.",
                field="job_opening",
                details={"provided_job_opening": data["job_opening"], "app_job_opening": app_doc.job_opening},
            )

        interview_data = dict(data)
        interview_data["candidate"] = app_doc.candidate
        interview_data["job_opening"] = app_doc.job_opening
        interview_data["company"] = app_doc.company

        self._validator.validate_create(interview_data)

        if not interview_data.get("status"):
            interview_data["status"] = "Scheduled"

        if not interview_data.get("interview_name"):
            interview_data["interview_name"] = f"INT-{frappe.generate_hash(length=8)}"

        doc = frappe.new_doc(DOCTYPE_INTERVIEW)
        self._apply_changed_fields(doc, interview_data)
        try:
            doc.insert(ignore_permissions=True)
        except DuplicateEntryError as exc:
            raise ATSConflictError(
                f"Interview conflict during creation.",
                details={"interview_name": interview_data.get("interview_name")},
            ) from exc

        log_activity(
            activity_type="Interview Scheduled",
            description=f"Interview {doc.name} ({doc.interview_type}) scheduled for candidate {doc.candidate}.",
            reference_doctype="Interview",
            reference_name=doc.name,
            candidate=doc.candidate,
            job_opening=doc.job_opening,
            job_application=doc.job_application,
            company=doc.company,
        )

        self._notify(
            title="Interview Scheduled",
            message=f"Interview {doc.name} scheduled for candidate {doc.candidate}.",
            priority="High",
            category="Interview",
            company=doc.company,
            entity_id=doc.name,
            action_url=f"/interviews/{doc.name}",
            action_label="View Interview",
        )

        return self._serialize_interview(doc, fields=_DETAIL_FIELDS)


    def schedule_interview(self, data: dict) -> dict:
        """Alias for create_interview."""
        return self.create_interview(data)

    def get_interview(self, interview_id: str) -> dict:
        """Retrieve a single Interview record by ID."""
        if not interview_id:
            raise ATSValidationError(
                "interview_id is required.", field="interview_id"
            )

        doc = self._get_or_raise(interview_id)
        self._assert_company_access(doc.company)
        return self._serialize_interview(doc, fields=_DETAIL_FIELDS)

    def update_interview(self, interview_id: str, data: dict) -> dict:
        """Update mutable fields of an existing Interview record."""
        if not interview_id:
            raise ATSValidationError(
                "interview_id is required.", field="interview_id"
            )

        self._validator.validate_update(data)
        doc = self._get_or_raise(interview_id)
        self._assert_company_access(doc.company)

        changed_fields = self._apply_changed_fields(doc, data)
        if changed_fields:
            try:
                doc.save(ignore_permissions=True)
            except DuplicateEntryError as exc:
                raise ATSConflictError(
                    f"Interview conflict during update.",
                    details={"interview_id": interview_id},
                ) from exc

        return self._serialize_interview(doc, fields=_DETAIL_FIELDS)

    def delete_interview(self, interview_id: str) -> None:
        """Delete an Interview record."""
        if not interview_id:
            raise ATSValidationError(
                "interview_id is required.", field="interview_id"
            )

        doc = self._get_or_raise(interview_id)
        self._assert_company_access(doc.company)

        try:
            frappe.delete_doc(
                DOCTYPE_INTERVIEW,
                interview_id,
                ignore_permissions=True,
                force=False,
            )
        except LinkExistsError as exc:
            raise ATSConflictError(
                f"Interview '{interview_id}' cannot be deleted because it is referenced by linked records.",
                details={"interview_id": interview_id},
            ) from exc

    def list_unscheduled_applications(self) -> list[dict]:
        """Return Job Applications in 'Interview' stage that do not have an Interview DocType record yet."""
        user = getattr(frappe.session, "user", "")
        current_comp = get_current_company() if user != "Administrator" else None

        app_filters = {"current_stage": "Interview"}
        if current_comp:
            app_filters["company"] = current_comp

        interview_apps = frappe.get_list(
            DOCTYPE_JOB_APPLICATION,
            filters=app_filters,
            fields=["name", "candidate", "job_opening", "company", "current_stage", "status", "applied_on", "creation"],
            order_by="creation desc",
            ignore_permissions=True,
        )

        if not interview_apps:
            return []

        int_filters = {}
        if current_comp:
            int_filters["company"] = current_comp

        existing_int_app_ids = {
            str(app_id).strip()
            for app_id in frappe.get_all(
                DOCTYPE_INTERVIEW,
                filters=int_filters,
                pluck="job_application",
                ignore_permissions=True,
            )
            if app_id
        }

        unscheduled = []
        for app in interview_apps:
            app_id = str(app["name"]).strip()
            if app_id not in existing_int_app_ids:
                unscheduled.append({
                    "job_application": app_id,
                    "candidate": str(app["candidate"]),
                    "job_opening": str(app["job_opening"]),
                    "company": app["company"],
                    "current_stage": app["current_stage"],
                    "application_status": app["status"],
                    "status": "Not Scheduled",
                    "interview_status": "Not Scheduled",
                    "applied_on": str(app.get("applied_on") or app.get("creation") or ""),
                })

        return unscheduled

    def list_interviews(
        self,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
        filters: dict | None = None,
        order_by: str = "creation",
        order_dir: str = "desc",
    ) -> dict:
        """Return a paginated list of Interview records with company scoping."""
        page, page_size = self._sanitise_pagination(page, page_size)
        order_clause = self._sanitise_order_by(order_by, order_dir)
        orm_filters = self._build_filters(filters or {})

        total = frappe.db.count(DOCTYPE_INTERVIEW, filters=orm_filters)

        records = frappe.get_list(
            DOCTYPE_INTERVIEW,
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

    def search_interviews(
        self,
        search: str,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
        filters: dict | None = None,
        order_by: str = "creation",
        order_dir: str = "desc",
    ) -> dict:
        """Search Interviews across candidate, company, job_opening, interviewer, scheduled_on, status."""
        if not search or not search.strip():
            raise ATSValidationError("Search term is required.", field="search")

        page, page_size = self._sanitise_pagination(page, page_size)
        order_clause = self._sanitise_order_by(order_by, order_dir)
        orm_filters = self._build_filters(filters or {})

        escaped_search = search.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        term = f"%{escaped_search}%"
        or_filters = [[field, "like", term] for field in SEARCHABLE_FIELDS]

        total = len(
            frappe.get_list(
                DOCTYPE_INTERVIEW,
                filters=orm_filters,
                or_filters=or_filters,
                fields=["name"],
                ignore_permissions=True,
            )
        )

        records = frappe.get_list(
            DOCTYPE_INTERVIEW,
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

    def change_status(self, interview_id: str, new_status: str) -> dict:
        """Change the status of an Interview atomically."""
        if not interview_id:
            raise ATSValidationError(
                "interview_id is required.", field="interview_id"
            )

        if not new_status:
            raise ATSValidationError(
                "new_status is required.", field="new_status"
            )

        self._validator.validate_status(new_status)
        doc = self._get_or_raise(interview_id)
        self._assert_company_access(doc.company)

        frappe.db.set_value(
            DOCTYPE_INTERVIEW,
            interview_id,
            "status",
            new_status,
            update_modified=True,
        )

        doc.reload()

        self._notify(
            title="Interview Status Updated",
            message=f"Interview {doc.name} status updated to '{new_status}'.",
            priority="Medium",
            category="Interview",
            company=doc.company,
            entity_id=doc.name,
            action_url=f"/interviews/{doc.name}",
            action_label="View Interview",
        )

        return self._serialize_interview(doc, fields=_DETAIL_FIELDS)

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
                    "entity_type": "Interview",
                    "entity_id": entity_id,
                    "action_url": action_url,
                    "action_label": action_label,
                },
                company=target_company,
                recipient=recipient,
                created_by=getattr(frappe.session, "user", "System"),
            )
        except Exception as exc:
            frappe.logger().error(f"Interview notification error: {exc}")


    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _get_or_raise(self, interview_id: str):
        """Fetch an Interview document or raise ATSNotFoundError."""
        if not frappe.db.exists(DOCTYPE_INTERVIEW, interview_id):
            raise ATSNotFoundError(
                f"Interview '{interview_id}' was not found.",
                doctype=DOCTYPE_INTERVIEW,
                name=interview_id,
            )
        return frappe.get_doc(DOCTYPE_INTERVIEW, interview_id)

    @staticmethod
    def _assert_company_access(company: str) -> None:
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

    @staticmethod
    def _serialize_interview(doc, fields: list[str]) -> dict:
        """Serialise an Interview document to a clean dict excluding Frappe metadata."""
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
        """Construct ORM filters for Interview queries with company scoping."""
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

        if filters.get("interviewer"):
            orm["interviewer"] = filters["interviewer"]

        if filters.get("scheduled_on"):
            orm["scheduled_on"] = filters["scheduled_on"]

        if filters.get("status"):
            orm["status"] = filters["status"]

        if filters.get("interview_type"):
            orm["interview_type"] = filters["interview_type"]

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
