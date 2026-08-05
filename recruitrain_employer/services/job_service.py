# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.services.job_service
==========================================

Job Opening Business Logic Service.

Architecture
------------
All database operations for the Job Opening domain are centralised here.
The API layer (``recruitrain_employer.api.jobs``) must not access
``frappe.get_doc``, ``frappe.get_all``, or ``frappe.db`` directly.

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
    JobValidator / Resolvers  ← Input validation & master resolution
      │
      ▼
    Frappe ORM / MariaDB
"""

from __future__ import annotations

import frappe
from frappe.exceptions import DuplicateEntryError, LinkExistsError

from recruitrain_employer.utils.constants import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    DOCTYPE_JOB_OPENING,
    MAX_PAGE_SIZE,
)
from recruitrain_employer.utils.exceptions import (
    ATSConflictError,
    ATSNotFoundError,
    ATSValidationError,
)
from recruitrain_employer.utils.permissions import get_current_company
from recruitrain_employer.validators.job_validator import JobValidator, normalize_job_payload


# ---------------------------------------------------------------------------
# Module-Level Constants
# ---------------------------------------------------------------------------

SEARCHABLE_FIELDS: tuple[str, ...] = (
    "job_title",
    "job_code",
    "company",
    "department",
    "profession",
    "employment_type",
    "city",
    "state",
    "country",
)

ALLOWED_SORT_FIELDS: frozenset[str] = frozenset(
    [
        "creation",
        "modified",
        "job_title",
        "job_code",
        "company",
        "department",
        "profession",
        "employment_type",
        "status",
        "target_joining_date",
        "minimum_salary",
        "maximum_salary",
        "number_of_openings",
        "minimum_experience",
        "maximum_experience",
        "city",
        "state",
        "country",
        "published_at",
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
    "job_title",
    "job_code",
    "company",
    "department",
    "profession",
    "employment_type",
    "city",
    "state",
    "country",
    "remote",
    "hybrid",
    "status",
    "target_joining_date",
    "currency",
    "minimum_salary",
    "maximum_salary",
    "number_of_openings",
    "published",
    "published_at",
    "published_by",
    "featured_job",
]

_DETAIL_FIELDS: list[str] = [
    "name",
    "job_title",
    "job_code",
    "company",
    "department",
    "profession",
    "employment_type",
    "industry",
    "number_of_openings",
    "hiring_manager",
    "recruiter",
    "target_joining_date",
    "minimum_experience",
    "maximum_experience",
    "currency",
    "minimum_salary",
    "maximum_salary",
    "salary_negotiable",
    "country",
    "state",
    "city",
    "remote",
    "hybrid",
    "job_summary",
    "responsibilities",
    "requirements",
    "benefits",
    "status",
    "published",
    "published_at",
    "published_by",
    "featured_job",
]


class JobService:
    """Encapsulates business logic for Job Opening operations."""

    def __init__(self) -> None:
        self._validator = JobValidator()
        try:
            from recruitrain_employer.services.master_seed_service import ensure_master_records_exist
            ensure_master_records_exist()
        except Exception:
            pass

    def save_draft(self, data: dict, job_id: str | None = None) -> dict:
        """Save a Job Opening draft (create new or update existing).

        Draft saving does NOT require mandatory publish fields.
        Company is strictly resolved from `get_current_company()`.
        Once a job is published, save_draft NEVER overwrites status/published/published_at
        unless explicitly requested by passing status="Draft" or published=0.
        Saving a draft NEVER emits notifications.
        """
        normalize_job_payload(data)
        job_id = job_id or data.get("job_id") or data.get("name")
        data_clean = {k: v for k, v in data.items() if k not in ("job_id", "name")}

        current_company = get_current_company()
        data_clean["company"] = current_company

        self._validator.validate_draft(data_clean)

        if job_id and frappe.db.exists(DOCTYPE_JOB_OPENING, job_id):
            doc = frappe.get_doc(DOCTYPE_JOB_OPENING, job_id)

            # Prevent overwriting published status on existing published jobs during autosave/draft update
            if getattr(doc, "published", 0) == 1 or getattr(doc, "status", "") == "Open":
                if "status" not in data or data.get("status") is None:
                    data_clean.pop("status", None)
                if "published" not in data or data.get("published") is None:
                    data_clean.pop("published", None)

            self._apply_changed_fields(doc, data_clean)
            if not doc.status:
                doc.status = "Draft"
            doc.company = current_company
            doc.flags.ignore_mandatory = True
            doc.save(ignore_permissions=True)
            frappe.db.commit()
        else:
            if not data_clean.get("job_code"):
                data_clean["job_code"] = self._generate_job_code()
            else:
                self._assert_job_code_unique(data_clean["job_code"])

            if not data_clean.get("job_title"):
                data_clean["job_title"] = "Untitled Job"

            if "status" not in data_clean:
                data_clean["status"] = "Draft"
            if "published" not in data_clean:
                data_clean["published"] = 0

            doc = frappe.new_doc(DOCTYPE_JOB_OPENING)
            self._apply_changed_fields(doc, data_clean)
            doc.company = current_company
            doc.flags.ignore_mandatory = True
            try:
                doc.insert(ignore_permissions=True)
                frappe.db.commit()
            except DuplicateEntryError as exc:
                frappe.db.rollback()
                raise ATSConflictError(
                    f"A Job Opening with job_code '{doc.job_code}' already exists.",
                    details={"field": "job_code", "value": doc.job_code},
                ) from exc

        metrics = self._get_batch_ats_metrics([doc.name])
        return self._serialize_job(doc, fields=_DETAIL_FIELDS, metrics=metrics.get(doc.name))

    def create_job(self, data: dict) -> dict:
        """Create a new Job Opening record.

        Company is strictly resolved from `get_current_company()`.
        If status is 'Draft' (or unspecified & published=0), delegates to `save_draft`.
        If status is 'Open' or published=1, enforces strict publish validation, saves, commits,
        and emits notification.
        """
        normalize_job_payload(data)
        current_company = get_current_company()
        data["company"] = current_company

        status = data.get("status", "Draft")
        is_published = bool(data.get("published"))

        if status != "Open" and not is_published:
            return self.save_draft(data)

        self._validator.validate_publish(data)

        if data.get("job_code"):
            self._assert_job_code_unique(data["job_code"])
        else:
            data["job_code"] = self._generate_job_code()

        data["status"] = "Open"
        data["published"] = 1
        data["published_at"] = frappe.utils.now_datetime()
        data["published_by"] = getattr(frappe.session, "user", "Administrator")

        doc = frappe.new_doc(DOCTYPE_JOB_OPENING)
        self._apply_changed_fields(doc, data)
        doc.company = current_company

        try:
            doc.insert(ignore_permissions=True)
            frappe.db.commit()
        except DuplicateEntryError as exc:
            frappe.db.rollback()
            raise ATSConflictError(
                f"A Job Opening with job_code '{data.get('job_code')}' already exists.",
                details={"field": "job_code", "value": data.get("job_code")},
            ) from exc

        # Emit notification strictly AFTER successful commit
        self._notify(
            title="Job Opening Published",
            message=f"Job opening '{doc.job_title}' ({doc.name}) is live and published.",
            priority="High",
            category="Job",
            company=doc.company,
            entity_id=doc.name,
            action_url=f"/jobs/{doc.name}",
            action_label="View Job",
        )

        metrics = self._get_batch_ats_metrics([doc.name])
        return self._serialize_job(doc, fields=_DETAIL_FIELDS, metrics=metrics.get(doc.name))

    def get_job(self, job_id: str) -> dict:
        """Retrieve a full Job Opening record by ID."""
        if not job_id:
            raise ATSValidationError("job_id is required.", field="job_id")

        doc = self._get_or_raise(job_id)
        metrics = self._get_batch_ats_metrics([job_id])
        return self._serialize_job(doc, fields=_DETAIL_FIELDS, metrics=metrics.get(job_id))

    def update_job(self, job_id: str, data: dict) -> dict:
        """Apply a partial update to an existing Job Opening record.

        Updates only supplied fields, never resets status or published flag, and never overwrites unchanged values.
        """
        if not job_id:
            raise ATSValidationError("job_id is required.", field="job_id")

        normalize_job_payload(data)
        current_company = get_current_company()
        data["company"] = current_company

        self._validator.validate_update(data)

        doc = self._get_or_raise(job_id)
        prev_status = doc.status

        # Apply only supplied changed fields
        changed_fields = self._apply_changed_fields(doc, data)
        doc.company = current_company

        if changed_fields:
            if doc.status == "Draft":
                doc.flags.ignore_mandatory = True
            try:
                doc.save(ignore_permissions=True)
                frappe.db.commit()
            except DuplicateEntryError as exc:
                frappe.db.rollback()
                raise ATSConflictError(
                    f"Job Opening conflict during update.",
                    details={"job_id": job_id},
                ) from exc

            # Emit notification only if important business status change occurred (e.g. Closed or Paused)
            if "status" in changed_fields and doc.status != prev_status:
                self._notify(
                    title=f"Job Opening {doc.status}",
                    message=f"Job opening '{doc.job_title}' status changed to {doc.status}.",
                    priority="Medium",
                    category="Job",
                    company=doc.company,
                    entity_id=doc.name,
                    action_url=f"/jobs/{doc.name}",
                    action_label="View Job",
                )

        metrics = self._get_batch_ats_metrics([job_id])
        return self._serialize_job(doc, fields=_DETAIL_FIELDS, metrics=metrics.get(job_id))

    def publish_job(self, job_id: str, data: dict | None = None) -> dict:
        """Publish a Job Opening, enforcing strict publish validation."""
        if not job_id:
            raise ATSValidationError("job_id is required.", field="job_id")
        doc = self._get_or_raise(job_id)

        current_company = get_current_company()

        if data:
            normalize_job_payload(data)
            self._apply_changed_fields(doc, data)

        doc.company = current_company

        combined_payload = {
            "job_title": doc.job_title,
            "company": current_company,
            "employment_type": doc.employment_type,
            "job_summary": doc.job_summary,
            "responsibilities": getattr(doc, "responsibilities", None),
            "requirements": getattr(doc, "requirements", None),
            "status": "Open",
            "published": 1,
            "salary_min": getattr(doc, "minimum_salary", None),
            "salary_max": getattr(doc, "maximum_salary", None),
            "opening_date": getattr(doc, "opening_date", None),
            "closing_date": getattr(doc, "closing_date", None),
            "department": getattr(doc, "department", None),
            "profession": getattr(doc, "profession", None),
        }
        self._validator.validate_publish(combined_payload)

        if combined_payload.get("employment_type"):
            doc.employment_type = combined_payload["employment_type"]
        if combined_payload.get("department"):
            doc.department = combined_payload["department"]
        if combined_payload.get("profession"):
            doc.profession = combined_payload["profession"]

        doc.published = 1
        doc.status = "Open"
        doc.published_at = frappe.utils.now_datetime()
        doc.published_by = getattr(frappe.session, "user", "Administrator")

        doc.save(ignore_permissions=True)
        frappe.db.commit()

        # Emit notification strictly AFTER successful commit
        self._notify(
            title="Job Published",
            message=f"Job opening '{doc.job_title}' is now live and published.",
            priority="High",
            category="Job",
            company=doc.company,
            entity_id=doc.name,
            action_url=f"/jobs/{doc.name}",
            action_label="View Job",
        )

        metrics = self._get_batch_ats_metrics([job_id])
        return self._serialize_job(doc, fields=_DETAIL_FIELDS, metrics=metrics.get(job_id))

    def close_job(self, job_id: str) -> dict:
        """Close a Job Opening, setting status='Closed'."""
        if not job_id:
            raise ATSValidationError("job_id is required.", field="job_id")
        doc = self._get_or_raise(job_id)
        doc.status = "Closed"
        doc.save(ignore_permissions=True)
        frappe.db.commit()

        self._notify(
            title="Job Opening Closed",
            message=f"Job opening '{doc.job_title}' has been closed.",
            priority="Medium",
            category="Job",
            company=doc.company,
            entity_id=doc.name,
            action_url=f"/jobs/{doc.name}",
            action_label="View Job",
        )
        metrics = self._get_batch_ats_metrics([job_id])
        return self._serialize_job(doc, fields=_DETAIL_FIELDS, metrics=metrics.get(job_id))

    def delete_job(self, job_id: str) -> None:
        """Permanently delete a Job Opening record."""
        if not job_id:
            raise ATSValidationError("job_id is required.", field="job_id")

        self._get_or_raise(job_id)

        try:
            frappe.delete_doc(
                DOCTYPE_JOB_OPENING,
                job_id,
                ignore_permissions=True,
                force=False,
            )
            frappe.db.commit()
        except LinkExistsError as exc:
            frappe.db.rollback()
            raise ATSConflictError(
                f"Job Opening '{job_id}' cannot be deleted because it is "
                "referenced by one or more linked records. Please resolve those references first.",
                details={"job_id": job_id},
            ) from exc

    def list_jobs(
        self,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
        filters: dict | None = None,
        order_by: str = "creation",
        order_dir: str = "desc",
    ) -> dict:
        """Return a paginated, filtered list of Job Opening records scoped to company."""
        page, page_size = self._sanitise_pagination(page, page_size)
        order_clause = self._sanitise_order_by(order_by, order_dir)
        orm_filters = self._build_filters(filters or {})

        # Force company filter for company scoping
        current_company = get_current_company()
        orm_filters["company"] = current_company

        total = frappe.db.count(DOCTYPE_JOB_OPENING, filters=orm_filters)

        records = frappe.get_list(
            DOCTYPE_JOB_OPENING,
            filters=orm_filters,
            fields=_LIST_FIELDS,
            order_by=order_clause,
            limit_start=(page - 1) * page_size,
            limit_page_length=page_size,
            ignore_permissions=True,
        )

        job_ids = [r["name"] for r in records if "name" in r]
        batch_metrics = self._get_batch_ats_metrics(job_ids)

        data = [
            self._serialize_job(r, fields=_LIST_FIELDS, metrics=batch_metrics.get(r.get("name")))
            for r in records
        ]

        return {
            "data": data,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def search_jobs(
        self,
        search: str,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
        filters: dict | None = None,
        order_by: str = "creation",
        order_dir: str = "desc",
    ) -> dict:
        """Search Job Openings across SEARCHABLE_FIELDS using a single query string."""
        if not search or not search.strip():
            raise ATSValidationError("Search term is required.", field="search")

        page, page_size = self._sanitise_pagination(page, page_size)
        order_clause = self._sanitise_order_by(order_by, order_dir)
        orm_filters = self._build_filters(filters or {})

        current_company = get_current_company()
        orm_filters["company"] = current_company

        escaped_search = search.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        term = f"%{escaped_search}%"
        or_filters = [[field, "like", term] for field in SEARCHABLE_FIELDS]

        total = frappe.db.count(DOCTYPE_JOB_OPENING, filters=orm_filters, or_filters=or_filters)

        records = frappe.get_list(
            DOCTYPE_JOB_OPENING,
            filters=orm_filters,
            or_filters=or_filters,
            fields=_LIST_FIELDS,
            order_by=order_clause,
            limit_start=(page - 1) * page_size,
            limit_page_length=page_size,
            ignore_permissions=True,
        )

        job_ids = [r["name"] for r in records if "name" in r]
        batch_metrics = self._get_batch_ats_metrics(job_ids)

        data = [
            self._serialize_job(r, fields=_LIST_FIELDS, metrics=batch_metrics.get(r.get("name")))
            for r in records
        ]

        return {
            "data": data,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _get_or_raise(self, job_id: str):
        """Fetch a Job Opening document or raise ATSNotFoundError."""
        if not frappe.db.exists(DOCTYPE_JOB_OPENING, job_id):
            raise ATSNotFoundError(
                f"Job Opening '{job_id}' was not found.",
                doctype=DOCTYPE_JOB_OPENING,
                name=job_id,
            )
        return frappe.get_doc(DOCTYPE_JOB_OPENING, job_id)

    def _assert_job_code_unique(self, job_code: str) -> None:
        """Raise ATSConflictError if job_code is already taken."""
        if frappe.db.exists(DOCTYPE_JOB_OPENING, {"job_code": job_code}):
            raise ATSConflictError(
                f"A Job Opening with job_code '{job_code}' already exists.",
                details={"field": "job_code", "value": job_code},
            )

    @staticmethod
    def _generate_job_code() -> str:
        """Generate a unique job_code."""
        try:
            from frappe.model.naming import make_autoname
            return make_autoname("JOB-.#####")
        except Exception:
            import uuid
            return f"JOB-{uuid.uuid4().hex[:8].upper()}"

    @staticmethod
    def _notify(
        title: str,
        message: str,
        priority: str,
        category: str,
        company: str,
        entity_id: str,
        action_url: str,
        action_label: str,
    ) -> None:
        try:
            from recruitrain_employer.services.notification_service import NotificationService
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
                    "entity_type": "Job Opening",
                    "entity_id": entity_id,
                    "action_url": action_url,
                    "action_label": action_label,
                },
                company=target_company,
                recipient=recipient,
                created_by=getattr(frappe.session, "user", "System"),
            )
        except Exception as exc:
            frappe.logger().error(f"Job notification error: {exc}")

    @staticmethod
    def _get_batch_ats_metrics(job_ids: list[str]) -> dict[str, dict[str, int]]:
        """Calculate aggregated ATS summary metrics for a list of Job Opening IDs."""
        metrics = {
            jid: {
                "application_count": 0,
                "shortlisted_count": 0,
                "interview_count": 0,
                "offer_count": 0,
                "hired_count": 0,
                "rejected_count": 0,
            }
            for jid in job_ids
            if jid
        }
        if not metrics:
            return metrics

        valid_ids = list(metrics.keys())

        # 1. Job Application metrics
        app_rows = frappe.db.sql(
            """
            SELECT job_opening, current_stage, COUNT(*) AS cnt
            FROM `tabJob Application`
            WHERE job_opening IN %s
            GROUP BY job_opening, current_stage
            """,
            (valid_ids,),
            as_dict=True,
        )
        for row in app_rows:
            jid = row.get("job_opening")
            stage = row.get("current_stage")
            cnt = int(row.get("cnt") or 0)
            if jid in metrics:
                metrics[jid]["application_count"] += cnt
                if stage == "Shortlisted":
                    metrics[jid]["shortlisted_count"] += cnt
                elif stage == "Hired":
                    metrics[jid]["hired_count"] += cnt
                elif stage == "Rejected":
                    metrics[jid]["rejected_count"] += cnt

        # 2. Interview metrics
        interview_rows = frappe.db.sql(
            """
            SELECT job_opening, COUNT(*) AS cnt
            FROM `tabInterview`
            WHERE job_opening IN %s
            GROUP BY job_opening
            """,
            (valid_ids,),
            as_dict=True,
        )
        for row in interview_rows:
            jid = row.get("job_opening")
            cnt = int(row.get("cnt") or 0)
            if jid in metrics:
                metrics[jid]["interview_count"] = cnt

        # 3. Offer metrics
        offer_rows = frappe.db.sql(
            """
            SELECT job_opening, COUNT(*) AS cnt
            FROM `tabOffer`
            WHERE job_opening IN %s
            GROUP BY job_opening
            """,
            (valid_ids,),
            as_dict=True,
        )
        for row in offer_rows:
            jid = row.get("job_opening")
            cnt = int(row.get("cnt") or 0)
            if jid in metrics:
                metrics[jid]["offer_count"] = cnt

        return metrics

    @staticmethod
    def _serialize_job(doc, fields: list[str], metrics: dict | None = None) -> dict:
        """Serialise a Frappe Job Opening Document to a plain JSON-safe dict."""
        if isinstance(doc, dict):
            data = {
                field: doc.get(field)
                for field in fields
                if field not in _FRAPPE_METADATA_FIELDS and field in doc
            }
        else:
            data = {
                field: doc.get(field)
                for field in fields
                if field not in _FRAPPE_METADATA_FIELDS
            }

        if "job_summary" in data and "description" not in data:
            data["description"] = data["job_summary"]
        if "minimum_salary" in data and "salary_min" not in data:
            data["salary_min"] = data["minimum_salary"]
        if "maximum_salary" in data and "salary_max" not in data:
            data["salary_max"] = data["maximum_salary"]
        if "number_of_openings" in data and "number_of_positions" not in data:
            data["number_of_positions"] = data["number_of_openings"]

        loc_parts = [str(data[k]) for k in ("city", "state", "country") if data.get(k)]
        if loc_parts:
            data["location"] = ", ".join(loc_parts)
        elif data.get("remote"):
            data["location"] = "Remote"
        else:
            data["location"] = data.get("location", None)

        default_metrics = {
            "application_count": 0,
            "shortlisted_count": 0,
            "interview_count": 0,
            "offer_count": 0,
            "hired_count": 0,
            "rejected_count": 0,
        }
        if metrics:
            default_metrics.update(metrics)

        data.update(default_metrics)
        return data

    @staticmethod
    def _apply_changed_fields(doc, data: dict) -> dict:
        """Apply only genuinely changed fields onto a Frappe Document object, stripping unknown UI fields."""
        changed: dict = {}
        meta = frappe.get_meta(doc.doctype)

        normalized_data = dict(data)
        normalize_job_payload(normalized_data)

        for field, new_value in normalized_data.items():
            if not meta.has_field(field):
                continue
            current_value = doc.get(field)
            if current_value != new_value:
                setattr(doc, field, new_value)
                changed[field] = new_value
        return changed

    @staticmethod
    def _build_filters(filters: dict) -> dict:
        """Construct a Frappe ORM filter dict using valid DocType schema fields."""
        orm: dict = {}

        if filters.get("company"):
            orm["company"] = filters["company"]
        if filters.get("department"):
            orm["department"] = filters["department"]
        if filters.get("profession"):
            orm["profession"] = filters["profession"]
        if filters.get("employment_type"):
            orm["employment_type"] = filters["employment_type"]
        if filters.get("industry"):
            orm["industry"] = filters["industry"]
        if filters.get("status"):
            orm["status"] = filters["status"]
        if filters.get("city"):
            orm["city"] = filters["city"]
        if filters.get("state"):
            orm["state"] = filters["state"]
        if filters.get("country"):
            orm["country"] = filters["country"]
        if filters.get("remote") is not None:
            orm["remote"] = filters["remote"]
        if filters.get("hybrid") is not None:
            orm["hybrid"] = filters["hybrid"]
        if filters.get("published") is not None:
            orm["published"] = filters["published"]
        if filters.get("featured_job") is not None:
            orm["featured_job"] = filters["featured_job"]

        if filters.get("location") and not (filters.get("city") or filters.get("state") or filters.get("country")):
            orm["city"] = ["like", f"%{filters['location']}%"]

        return orm

    @staticmethod
    def _sanitise_pagination(page: int, page_size: int) -> tuple[int, int]:
        """Clamp page and page_size."""
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
        return page, page_size

    @staticmethod
    def _sanitise_order_by(order_by: str, order_dir: str) -> str:
        """Return validated ORDER BY clause string."""
        safe_field = order_by if order_by in ALLOWED_SORT_FIELDS else "creation"
        safe_dir = "asc" if str(order_dir).lower() == "asc" else "desc"
        return f"{safe_field} {safe_dir}"
