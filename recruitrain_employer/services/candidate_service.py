# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.services.candidate_service
================================================

Production-Grade Business Logic & ORM Service for Candidate Subsystem.
"""

from __future__ import annotations

from typing import Any
import frappe
from frappe.exceptions import DuplicateEntryError, LinkExistsError

from recruitrain_employer.normalizers.candidate_normalizer import normalize_candidate_payload
from recruitrain_employer.serializers.candidate_serializer import serialize_candidate
from recruitrain_employer.utils.constants import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    DOCTYPE_CANDIDATE,
    MAX_PAGE_SIZE,
)
from recruitrain_employer.utils.exceptions import (
    ATSCompanyNotFoundError,
    ATSConflictError,
    ATSNotFoundError,
    ATSPermissionError,
    ATSValidationError,
)
from recruitrain_employer.utils.activity_logger import log_activity
from recruitrain_employer.utils.permissions import get_current_company
from recruitrain_employer.validators.candidate_validator import CandidateValidator

SEARCHABLE_FIELDS: tuple[str, ...] = (
    "candidate_name",
    "first_name",
    "last_name",
    "email",
    "mobile_no",
    "profession",
    "current_company",
    "current_job_title",
    "city",
    "state",
    "country",
    "preferred_location",
)

ALLOWED_SORT_FIELDS: frozenset[str] = frozenset(
    [
        "creation",
        "modified",
        "candidate_name",
        "first_name",
        "last_name",
        "email",
        "status",
        "years_of_experience",
        "expected_salary",
    ]
)


class CandidateService:
    """Encapsulates business logic, transactional persistence, and company scoping for Candidates."""

    def __init__(self) -> None:
        self._validator = CandidateValidator()

    # ------------------------------------------------------------------
    # Company Scoping & Ownership Verification
    # ------------------------------------------------------------------

    def _get_company_scoped_candidate_names(self, company: str) -> list[str] | None:
        """Get candidate primary keys accessible to the specified company.

        A candidate is accessible if:
        1. Candidate.company == company OR
        2. Candidate has a Job Application with company == company.
        """
        if not company:
            return []

        # 1. Directly owned candidate names
        owned = frappe.get_all(
            DOCTYPE_CANDIDATE,
            filters={"company": company},
            pluck="name",
        )

        # 2. Candidate names linked via Job Applications
        applied = frappe.get_all(
            "Job Application",
            filters={"company": company},
            pluck="candidate",
        )

        combined = list(set(owned + [c for c in applied if c]))
        return combined

    def _assert_candidate_access(self, doc: Any, company: str | None = None) -> None:
        """Assert current authenticated user has access to this Candidate doc."""
        if not company:
            try:
                company = get_current_company()
            except Exception:
                # If guest/system, skip check if admin
                if getattr(frappe.session, "user", None) == "Administrator":
                    return
                raise ATSPermissionError("Authentication required.")

        doc_company = getattr(doc, "company", None)
        if doc_company and doc_company == company:
            return

        # Check application connection
        has_app = frappe.db.exists("Job Application", {"candidate": doc.name, "company": company})
        if not has_app and doc_company and doc_company != company:
            raise ATSPermissionError(
                f"Access denied. Candidate '{doc.name}' does not belong to company '{company}'.",
                details={"candidate_id": doc.name, "company": company},
            )

    def _get_or_raise(self, candidate_id: str) -> Any:
        """Fetch candidate document and enforce company permission check."""
        if not candidate_id:
            raise ATSValidationError("candidate_id is required.", field="candidate_id")

        if not frappe.db.exists(DOCTYPE_CANDIDATE, candidate_id):
            raise ATSNotFoundError(
                f"Candidate '{candidate_id}' does not exist.",
                details={"candidate_id": candidate_id},
            )

        doc = frappe.get_doc(DOCTYPE_CANDIDATE, candidate_id)
        self._assert_candidate_access(doc)
        return doc

    # ------------------------------------------------------------------
    # CRUD Methods
    # ------------------------------------------------------------------

    def create_candidate(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new Candidate record for the active company."""
        company = get_current_company()
        norm_data = self._validator.validate_create(data)

        # Force company ownership
        norm_data["company"] = company

        self._assert_email_unique(norm_data["email"], company=company)

        doc = frappe.new_doc(DOCTYPE_CANDIDATE)
        doc.update(norm_data)
        doc.company = company
        doc.status = norm_data.get("status") or "Active"

        first = (norm_data.get("first_name") or "").strip()
        last = (norm_data.get("last_name") or "").strip()
        c_name = (norm_data.get("candidate_name") or f"{first} {last}").strip()
        doc.candidate_name = c_name
        doc.candidate_id = norm_data.get("candidate_id") or c_name

        try:
            doc.insert(ignore_permissions=True)
        except DuplicateEntryError as exc:
            raise ATSConflictError(
                f"A Candidate with email '{norm_data.get('email')}' already exists.",
                details={"field": "email", "value": norm_data.get("email")},
            ) from exc

        # Calculate completeness
        completeness = self.get_profile_completeness(doc.name)
        doc.profile_completion = completeness.get("profile_completion", 0.0)

        self._notify(
            title="New Candidate Added",
            message=f"Candidate profile '{doc.first_name} {doc.last_name}' ({doc.name}) was created.",
            priority="Low",
            category="Candidate",
            company=company,
            entity_id=doc.name,
            action_url=f"/candidates/{doc.name}",
            action_label="View Candidate",
        )

        log_activity(
            activity_type="Candidate Created",
            description=f"Candidate profile '{doc.first_name} {doc.last_name}' created.",
            reference_doctype="Candidate",
            reference_name=doc.name,
            candidate=doc.name,
            company=company,
        )

        frappe.db.commit()

        batch_apps = self._get_batch_latest_applications([doc.name])
        return serialize_candidate(doc, include_subresources=True, latest_application=batch_apps.get(doc.name))

    def get_candidate(self, candidate_id: str) -> dict[str, Any]:
        """Retrieve a full Candidate profile by record name."""
        doc = self._get_or_raise(candidate_id)
        batch_apps = self._get_batch_latest_applications([candidate_id])
        return serialize_candidate(doc, include_subresources=True, latest_application=batch_apps.get(candidate_id))

    def update_candidate(self, candidate_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Apply partial update to an existing Candidate record."""
        doc = self._get_or_raise(candidate_id)
        old_status = doc.status

        norm_data = self._validator.validate_update(data)

        # If status change, validate FSM transition
        new_status = norm_data.get("status")
        if new_status and new_status != old_status:
            self._validator.validate_status_transition(old_status, new_status)

        # Apply scalar updates
        for k, v in norm_data.items():
            if k not in ("education", "experience", "skills", "languages", "certifications", "documents"):
                doc.set(k, v)

        # Non-destructive sub-resource updates if provided
        for sub_field in ("education", "experience", "skills", "languages", "certifications", "documents"):
            if sub_field in norm_data:
                self._update_child_table(doc, sub_field, norm_data[sub_field])

        doc.save(ignore_permissions=True)

        # Recalculate profile completion
        self.get_profile_completeness(doc.name)

        if new_status and new_status != old_status:
            self._notify(
                title="Candidate Status Updated",
                message=f"Candidate '{doc.first_name} {doc.last_name}' status changed to {new_status}.",
                priority="Medium",
                category="Candidate",
                company=doc.company,
                entity_id=doc.name,
                action_url=f"/candidates/{doc.name}",
                action_label="View Profile",
            )

        frappe.db.commit()

        batch_apps = self._get_batch_latest_applications([candidate_id])
        return serialize_candidate(doc, include_subresources=True, latest_application=batch_apps.get(candidate_id))

    def delete_candidate(self, candidate_id: str) -> dict[str, Any]:
        """
        Delete a Candidate record with full referential integrity protection.

        Business Rules:
        - Deletion is BLOCKED if the Candidate has any of the following linked records:
          Job Application, Interview, Offer, Candidate Note, Talent Pool membership,
          or Activity Log entries. These are permanent recruitment audit history.
        - If no protected relationships exist, hard deletion proceeds atomically.
        - The subscription usage counter is decremented via the on_trash hook
          (registered in hooks.py -> on_candidate_on_trash).
        - Frappe File records (resume, documents) are removed by Frappe's
          delete_doc cascade for child tables. Standalone File records linked
          via the 'resume' Attach field are NOT deleted automatically; they
          remain in Frappe's file manager as audit artifacts.

        Returns
        -------
        dict
            {name, deleted: True} on success.

        Raises
        ------
        ATSValidationError
            If candidate_id is missing.
        ATSNotFoundError
            If the candidate does not exist.
        ATSPermissionError
            If the caller does not have access to this candidate.
        ATSConflictError
            If linked recruitment records exist (machine-readable code:
            CANDIDATE_HAS_RECRUITMENT_HISTORY).
        """
        doc = self._get_or_raise(candidate_id)
        company = doc.company or get_current_company()

        # ------------------------------------------------------------------
        # Referential Integrity Check
        # Build a comprehensive picture of all linked records before ANY
        # deletion attempt. Fail fast with a single structured error that
        # lists every blocker so the caller has full context.
        # ------------------------------------------------------------------
        blocking_links: dict[str, int] = {}

        # 1. Job Applications (most critical - recruitment pipeline history)
        linked_apps = frappe.db.count("Job Application", {"candidate": candidate_id})
        if linked_apps > 0:
            blocking_links["job_applications"] = linked_apps

        # Check all potential blocking recruitment records
        for doctype, key in [
            ("Job Application", "job_applications"),
            ("Interview", "interviews"),
            ("Interview Feedback", "interview_feedback"),
            ("Offer", "offers"),
            ("Candidate Note", "candidate_notes"),
            ("Talent Pool Member", "talent_pool_memberships"),
        ]:
            if frappe.db.table_exists(doctype):
                count = frappe.db.count(doctype, {"candidate": candidate_id})
                if count > 0:
                    blocking_links[key] = count

        if blocking_links:
            parts = [f"{count} {doctype.replace('_', ' ')}" for doctype, count in blocking_links.items()]
            summary = ", ".join(parts)
            raise ATSConflictError(
                f"Candidate '{candidate_id}' cannot be deleted because they have linked recruitment records: "
                f"{summary}. Archive the candidate (set status to 'Archived') instead of deleting.",
                details={
                    "candidate_id": candidate_id,
                    "error_code": "CANDIDATE_HAS_RECRUITMENT_HISTORY",
                    "blocking_links": blocking_links,
                },
            )

        # Cleanup system creation activity logs prior to unlinked candidate deletion
        if frappe.db.table_exists("Activity Logs"):
            frappe.db.delete("Activity Logs", {"candidate": candidate_id})

        # ------------------------------------------------------------------
        # Atomic Deletion
        # Frappe's delete_doc is transactional within the current DB session.
        # It will:
        #   1. Delete all child table rows (education, experience, skills, etc.)
        #   2. Fire the on_trash hook -> on_candidate_on_trash
        #      -> SubscriptionService().decrement_usage(company, "candidates")
        #   3. Remove the Candidate document itself from tabCandidate
        #
        # We catch LinkExistsError as a last-resort safety net for any
        # FK links that are not covered by the explicit checks above.
        # ------------------------------------------------------------------
        try:
            frappe.delete_doc(DOCTYPE_CANDIDATE, candidate_id, ignore_permissions=True)
            frappe.db.commit()
        except LinkExistsError as exc:
            raise ATSConflictError(
                f"Candidate '{candidate_id}' is linked to other records and cannot be deleted. "
                "Archive this candidate instead.",
                details={
                    "candidate_id": candidate_id,
                    "error_code": "CANDIDATE_HAS_RECRUITMENT_HISTORY",
                    "frappe_error": str(exc),
                },
            ) from exc

        return {"name": candidate_id, "deleted": True}

    # ------------------------------------------------------------------
    # Sub-Resource Non-Destructive Management
    # ------------------------------------------------------------------

    def _update_child_table(self, doc: Any, child_field: str, items: list[dict[str, Any]]) -> None:
        """Update child table rows in-place without destructive full resets."""
        if not isinstance(items, list):
            return

        existing_rows = {row.name: row for row in doc.get(child_field) or [] if getattr(row, "name", None)}

        for item in items:
            row_id = item.get("name")
            if row_id and row_id in existing_rows:
                # Update existing row
                child_doc = existing_rows[row_id]
                for k, v in item.items():
                    if k not in ("name", "doctype", "parent", "parentfield", "parenttype"):
                        child_doc.set(k, v)
            else:
                # Append new row
                doc.append(child_field, item)

    def update_subresource(self, candidate_id: str, sub_field: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        """Dedicated helper for endpoint sub-resource updates."""
        doc = self._get_or_raise(candidate_id)
        val_method = getattr(self._validator, f"validate_{sub_field}", None)
        if callable(val_method):
            val_method(items)
        self._update_child_table(doc, sub_field, items)
        doc.save(ignore_permissions=True)
        self.get_profile_completeness(doc.name)
        frappe.db.commit()
        return serialize_candidate(doc, include_subresources=True)

    # ------------------------------------------------------------------
    # Search, List & Filter Operations
    # ------------------------------------------------------------------

    def list_candidates(
        self,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
        order_by: str = "creation desc",
        status: str | None = None,
        profession: str | None = None,
        employment_type: str | None = None,
        country: str | None = None,
        search_term: str | None = None,
    ) -> dict[str, Any]:
        """Company-scoped, paginated, filtered listing of candidates."""
        user = getattr(frappe.session, "user", "Guest")
        frappe.logger().info(f"[CandidateService Stage 1] Session User: {user}")
        company = get_current_company()
        frappe.logger().info(f"[CandidateService Stage 2] Resolved Company: {company}")
        candidate_ids = self._get_company_scoped_candidate_names(company)

        if candidate_ids is not None and len(candidate_ids) == 0:
            frappe.logger().info(f"[CandidateService Stage 3] No accessible candidate IDs for company '{company}'.")
            return {"items": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}

        filters: dict[str, Any] = {}
        if candidate_ids is not None:
            filters["name"] = ["in", candidate_ids]

        if status:
            filters["status"] = status
        if profession:
            filters["profession"] = profession
        if employment_type:
            filters["employment_type"] = employment_type
        if country:
            filters["country"] = country

        page, page_size = self._sanitise_pagination(page, page_size)
        order_by = self._sanitise_order_by(order_by)
        start = (page - 1) * page_size
        frappe.logger().info(f"[CandidateService Stage 4] Applied Filters: {filters}")

        if search_term and search_term.strip():
            term = f"%{search_term.strip()}%"
            or_filters = [[field, "like", term] for field in SEARCHABLE_FIELDS]
            total = len(
                frappe.get_list(
                    DOCTYPE_CANDIDATE,
                    filters=filters,
                    or_filters=or_filters,
                    fields=["name"],
                    limit_page_length=0,
                    ignore_permissions=True,
                )
            )
            records = frappe.get_list(
                DOCTYPE_CANDIDATE,
                filters=filters,
                or_filters=or_filters,
                fields=["name"],
                order_by=order_by,
                start=start,
                page_length=page_size,
                ignore_permissions=True,
            )
        else:
            total = frappe.db.count(DOCTYPE_CANDIDATE, filters=filters)
            records = frappe.get_list(
                DOCTYPE_CANDIDATE,
                filters=filters,
                fields=["name"],
                order_by=order_by,
                start=start,
                page_length=page_size,
                ignore_permissions=True,
            )

        names = [r["name"] for r in records]
        frappe.logger().info(f"[CandidateService Stage 5] Executing ORM get_doc for candidate names: {names}")
        docs = [frappe.get_doc(DOCTYPE_CANDIDATE, n) for n in names]
        batch_apps = self._get_batch_latest_applications(names)

        items = [
            serialize_candidate(doc, include_subresources=False, latest_application=batch_apps.get(doc.name))
            for doc in docs
        ]

        total_pages = (total + page_size - 1) // page_size if total > 0 else 0

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def list_international_candidates(
        self,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
        order_by: str = "creation desc",
    ) -> dict[str, Any]:
        """List company-scoped international candidates using ORM filters."""
        company = get_current_company()
        candidate_ids = self._get_company_scoped_candidate_names(company)
        if candidate_ids is not None and len(candidate_ids) == 0:
            return {"items": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}

        base_filters: dict[str, Any] = {}
        if candidate_ids is not None:
            base_filters["name"] = ["in", candidate_ids]

        or_filters = [
            ["nationality", "!=", "India"],
            ["country", "!=", "India"],
            ["visa_status", "is", "set"],
            ["work_permit", "=", 1],
        ]

        page, page_size = self._sanitise_pagination(page, page_size)
        order_by = self._sanitise_order_by(order_by)
        start = (page - 1) * page_size

        total = len(frappe.get_list(DOCTYPE_CANDIDATE, filters=base_filters, or_filters=or_filters, fields=["name"], limit_page_length=0))
        records = frappe.get_list(
            DOCTYPE_CANDIDATE,
            filters=base_filters,
            or_filters=or_filters,
            fields=["name"],
            order_by=order_by,
            start=start,
            page_length=page_size,
        )

        names = [r["name"] for r in records]
        docs = [frappe.get_doc(DOCTYPE_CANDIDATE, n) for n in names]
        batch_apps = self._get_batch_latest_applications(names)

        items = [
            serialize_candidate(doc, include_subresources=False, latest_application=batch_apps.get(doc.name))
            for doc in docs
        ]

        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        return {"items": items, "total": total, "page": page, "page_size": page_size, "total_pages": total_pages}

    def list_domestic_candidates(
        self,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
        order_by: str = "creation desc",
    ) -> dict[str, Any]:
        """List company-scoped domestic candidates using ORM filters."""
        company = get_current_company()
        candidate_ids = self._get_company_scoped_candidate_names(company)
        if candidate_ids is not None and len(candidate_ids) == 0:
            return {"items": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}

        base_filters: dict[str, Any] = {"country": "India", "work_permit": 0}
        if candidate_ids is not None:
            base_filters["name"] = ["in", candidate_ids]

        page, page_size = self._sanitise_pagination(page, page_size)
        order_by = self._sanitise_order_by(order_by)
        start = (page - 1) * page_size

        total = frappe.db.count(DOCTYPE_CANDIDATE, filters=base_filters)
        records = frappe.get_list(
            DOCTYPE_CANDIDATE,
            filters=base_filters,
            fields=["name"],
            order_by=order_by,
            start=start,
            page_length=page_size,
        )

        names = [r["name"] for r in records]
        docs = [frappe.get_doc(DOCTYPE_CANDIDATE, n) for n in names]
        batch_apps = self._get_batch_latest_applications(names)

        items = [
            serialize_candidate(doc, include_subresources=False, latest_application=batch_apps.get(doc.name))
            for doc in docs
        ]

        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        return {"items": items, "total": total, "page": page, "page_size": page_size, "total_pages": total_pages}

    # ------------------------------------------------------------------
    # Profile Completeness Calculation
    # ------------------------------------------------------------------

    def get_profile_completeness(self, candidate_id: str) -> dict[str, Any]:
        """Compute profile completion percentage and write back to database."""
        doc = frappe.get_doc(DOCTYPE_CANDIDATE, candidate_id)

        weights = {
            "personal": 20,
            "contact": 15,
            "professional": 15,
            "education": 15,
            "experience": 15,
            "skills": 10,
            "documents": 10,
        }

        score = 0.0

        # Personal (first_name, last_name, dob)
        if doc.first_name and doc.last_name and doc.date_of_birth:
            score += weights["personal"]

        # Contact (email, mobile_no, address_line_1, city)
        if doc.email and doc.mobile_no and doc.address_line_1 and doc.city:
            score += weights["contact"]

        # Professional (current_job_title, years_of_experience, profession)
        if doc.current_job_title or doc.years_of_experience or doc.profession:
            score += weights["professional"]

        # Child tables
        if doc.get("education") and len(doc.education) > 0:
            score += weights["education"]
        if doc.get("experience") and len(doc.experience) > 0:
            score += weights["experience"]
        if doc.get("skills") and len(doc.skills) > 0:
            score += weights["skills"]
        if doc.resume or (doc.get("documents") and len(doc.documents) > 0):
            score += weights["documents"]

        final_score = round(score, 1)
        doc.profile_completion = final_score

        if frappe.db.get_value(DOCTYPE_CANDIDATE, candidate_id, "profile_completion") != final_score:
            frappe.db.set_value(DOCTYPE_CANDIDATE, candidate_id, "profile_completion", final_score, update_modified=False)

        return {"candidate_id": candidate_id, "profile_completion": final_score}

    # ------------------------------------------------------------------
    # Helpers & Notifications
    # ------------------------------------------------------------------

    def _assert_email_unique(self, email: str, company: str | None = None) -> None:
        """Assert email is unique within the company scope."""
        filters = {"email": email}
        if company:
            filters["company"] = company
        if frappe.db.exists(DOCTYPE_CANDIDATE, filters):
            raise ATSConflictError(
                f"A Candidate with email '{email}' already exists.",
                details={"field": "email", "value": email},
            )

    def _get_batch_latest_applications(self, candidate_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Batch fetch latest Job Application for a list of candidate IDs."""
        if not candidate_ids:
            return {}

        apps = frappe.get_all(
            "Job Application",
            filters={"candidate": ["in", candidate_ids]},
            fields=["name", "candidate", "job_opening", "status", "creation"],
            order_by="creation desc",
        )

        result: dict[str, dict[str, Any]] = {}
        for app in apps:
            cid = app["candidate"]
            if cid not in result:
                result[cid] = app
        return result

    def _sanitise_pagination(self, page: Any, page_size: Any) -> tuple[int, int]:
        try:
            p = max(1, int(page))
        except (ValueError, TypeError):
            p = DEFAULT_PAGE

        try:
            ps = min(MAX_PAGE_SIZE, max(1, int(page_size)))
        except (ValueError, TypeError):
            ps = DEFAULT_PAGE_SIZE

        return p, ps

    def _sanitise_order_by(self, order_by: str | None) -> str:
        """Sanitize and validate order_by string against allowed sort fields."""
        if not order_by or not isinstance(order_by, str):
            return "creation desc"

        parts = order_by.strip().split()
        if not parts:
            return "creation desc"

        field = parts[0].lower()
        direction = parts[1].lower() if len(parts) > 1 else "asc"

        if field not in ALLOWED_SORT_FIELDS:
            field = "creation"

        if direction not in ("asc", "desc"):
            direction = "desc"

        return f"{field} {direction}"

    def _notify(
        self,
        title: str,
        message: str,
        priority: str,
        category: str,
        company: str,
        entity_id: str,
        action_url: str | None = None,
        action_label: str | None = None,
    ) -> None:
        """Safe notification dispatcher."""
        try:
            from recruitrain_employer.services.notification_service import NotificationService

            NotificationService().create_notification(
                title=title,
                message=message,
                priority=priority,
                category=category,
                company=company,
                entity_type="Candidate",
                entity_id=entity_id,
                action_url=action_url,
                action_label=action_label,
            )
        except Exception as exc:
            frappe.logger().error(f"[CandidateService] Notification failed: {exc}")
