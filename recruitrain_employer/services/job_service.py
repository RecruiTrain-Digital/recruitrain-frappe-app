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
    JobValidator              ← Input validation
      │
      ▼
    Frappe ORM / MariaDB

Serializer Safety
-----------------
``_serialize_job`` actively excludes Frappe internal metadata fields
(``owner``, ``modified_by``, ``creation``, ``modified``, ``idx``,
``docstatus``, ``doctype``, ``parent``, ``parentfield``, ``parenttype``)
from every response.  Only business-facing fields defined in ``_LIST_FIELDS``
or ``_DETAIL_FIELDS`` are returned.  The exclusion set is applied as a
second gate regardless of what ``fields`` is passed.

Changed-Field Tracking
-----------------------
``_apply_changed_fields`` writes only fields whose values have actually
changed, skipping identical values.  This prevents unnecessary Frappe
dirty-field tracking and returns a ``dict`` ready for Activity Log diffing
in a future sprint.

Scope — Sprint: Job Opening Management Foundation
--------------------------------------------------
This sprint implements CRUD, listing, and searching for Job Openings.

Out of scope (implemented in future sprints):
- Job Applications
- Interview Scheduling
- Candidate Matching
- Offer Generation
- Publishing / approval workflow
- Notifications and Activity Logs
- Permissions / company-scoped access control
- Analytics

DocTypes Used
-------------
- Job Opening
- Company   (existence check in validator)
- Department  (existence check in validator)

Frappe APIs Used
----------------
- ``frappe.new_doc()``       — new document instantiation
- ``frappe.get_doc()``       — single-record fetch and mutation
- ``frappe.get_list()``      — paginated, filtered listing
- ``frappe.db.exists()``     — lightweight existence check
- ``frappe.db.count()``      — total-row count for pagination
- ``frappe.delete_doc()``    — safe record deletion
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
from recruitrain_employer.validators.job_validator import JobValidator, normalize_job_payload


# ---------------------------------------------------------------------------
# Module-Level Constants
# ---------------------------------------------------------------------------

#: Fields used to search across Job Opening records.
#: To add a new searchable field, append it here — no other changes needed.
#: Search uses LIKE with a lowercased term for case-insensitive matching.
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

#: Fields callers may pass to ``order_by``.
#: Any value not in this set is silently replaced with ``"creation"``
#: to prevent malformed queries.
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
    ]
)

#: Frappe internal metadata fields that must never appear in API responses.
#: Applied as a second exclusion gate in ``_serialize_job`` — defence-in-depth
#: against accidental exposure of system data.
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

#: Fields included in list and search result rows (lightweight projection).
#: Must not overlap with ``_FRAPPE_METADATA_FIELDS``.
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
    "featured_job",
]

#: Fields returned in a full Job Opening detail response.
#: Must not overlap with ``_FRAPPE_METADATA_FIELDS``.
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
    "featured_job",
]


class JobService:
    """Encapsulates business logic for Job Opening operations.

    All database reads and writes for the Job Opening domain go through
    this class.  No DocType access is permitted in the API layer.

    Usage
    -----
    ::

        service = JobService()
        job = service.get_job("JOB-0001")
    """

    def __init__(self) -> None:
        self._validator = JobValidator()
        try:
            from recruitrain_employer.services.master_seed_service import ensure_master_records_exist
            ensure_master_records_exist()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # CRUD Methods
    # ------------------------------------------------------------------

    def save_draft(self, data: dict, job_id: str | None = None) -> dict:
        """Save a Job Opening draft (create new or update existing).

        Draft saving does NOT require mandatory publish fields (job_title,
        employment_type, job_summary). Incomplete payloads are accepted cleanly.
        """
        normalize_job_payload(data)
        job_id = job_id or data.get("job_id") or data.get("name")
        data_clean = {k: v for k, v in data.items() if k not in ("job_id", "name")}

        self._validator.validate_draft(data_clean)

        if job_id and frappe.db.exists(DOCTYPE_JOB_OPENING, job_id):
            doc = frappe.get_doc(DOCTYPE_JOB_OPENING, job_id)
            self._apply_changed_fields(doc, data_clean)
            if not doc.status:
                doc.status = "Draft"
            doc.flags.ignore_mandatory = True
            doc.save(ignore_permissions=True)
        else:
            if not data_clean.get("job_code"):
                data_clean["job_code"] = self._generate_job_code()
            else:
                self._assert_job_code_unique(data_clean["job_code"])

            from recruitrain_employer.utils.permissions import get_current_company
            data_clean["company"] = get_current_company()

            if not data_clean.get("job_title"):
                data_clean["job_title"] = "Untitled Job"

            if "status" not in data_clean:
                data_clean["status"] = "Draft"

            doc = frappe.new_doc(DOCTYPE_JOB_OPENING)
            self._apply_changed_fields(doc, data_clean)
            doc.flags.ignore_mandatory = True
            try:
                doc.insert(ignore_permissions=True)
            except DuplicateEntryError as exc:
                raise ATSConflictError(
                    f"A Job Opening with job_code '{doc.job_code}' already exists.",
                    details={"field": "job_code", "value": doc.job_code},
                ) from exc

        metrics = self._get_batch_ats_metrics([doc.name])
        return self._serialize_job(doc, fields=_DETAIL_FIELDS, metrics=metrics.get(doc.name))

    def create_job(self, data: dict) -> dict:
        """Create a new Job Opening record.

        If status is 'Draft' (or unspecified), delegates to ``save_draft``.
        If status is 'Open' or published is set, enforces strict publish validation.
        """
        normalize_job_payload(data)
        status = data.get("status", "Draft")
        is_published = bool(data.get("published"))

        from recruitrain_employer.utils.permissions import get_current_company
        data["company"] = get_current_company()

        if status != "Open" and not is_published:
            return self.save_draft(data)

        self._validator.validate_publish(data)

        if data.get("job_code"):
            self._assert_job_code_unique(data["job_code"])
        else:
            data["job_code"] = self._generate_job_code()

        doc = frappe.new_doc(DOCTYPE_JOB_OPENING)
        self._apply_changed_fields(doc, data)
        try:
            doc.insert(ignore_permissions=True)
        except DuplicateEntryError as exc:
            raise ATSConflictError(
                f"A Job Opening with job_code '{data.get('job_code')}' already exists.",
                details={"field": "job_code", "value": data.get("job_code")},
            ) from exc

        self._notify(
            title="Job Opening Created",
            message=f"Job opening '{doc.job_title}' ({doc.name}) was created successfully.",
            priority="Medium",
            category="Job",
            company=doc.company,
            entity_id=doc.name,
            action_url=f"/jobs/{doc.name}",
            action_label="View Job",
        )

        return self._serialize_job(doc, fields=_DETAIL_FIELDS)


    def get_job(self, job_id: str) -> dict:
        """Retrieve a full Job Opening record by ID.

        Parameters
        ----------
        job_id : str
            The ``name`` (primary key) of the Job Opening record.

        Returns
        -------
        dict
            The Job Opening document serialised by ``_serialize_job()``.
            Only business-facing fields are included; Frappe metadata is
            excluded by the serialiser.

        Raises
        ------
        ATSValidationError
            If ``job_id`` is empty.
        ATSNotFoundError
            If no Job Opening with the given ID exists.

        TODO: Annotate with total application count once Job Applications
              sprint is implemented.
        """
        if not job_id:
            raise ATSValidationError("job_id is required.", field="job_id")

        doc = self._get_or_raise(job_id)
        metrics = self._get_batch_ats_metrics([job_id])
        return self._serialize_job(doc, fields=_DETAIL_FIELDS, metrics=metrics.get(job_id))

    def update_job(self, job_id: str, data: dict) -> dict:
        """Apply a partial update to an existing Job Opening record.

        Only fields whose values have **changed** from the current document
        are written. Identical values are skipped, preventing unnecessary
        dirty-field tracking.
        """
        if not job_id:
            raise ATSValidationError("job_id is required.", field="job_id")

        normalize_job_payload(data)
        self._validator.validate_update(data)

        doc = self._get_or_raise(job_id)

        # Apply only changed fields
        changed_fields = self._apply_changed_fields(doc, data)

        if changed_fields:
            if doc.status == "Draft":
                doc.flags.ignore_mandatory = True
            try:
                doc.save(ignore_permissions=True)
            except DuplicateEntryError as exc:
                raise ATSConflictError(
                    f"Job Opening conflict during update.",
                    details={"job_id": job_id},
                ) from exc

        metrics = self._get_batch_ats_metrics([job_id])
        return self._serialize_job(doc, fields=_DETAIL_FIELDS, metrics=metrics.get(job_id))

    # TODO: Replace hard delete with an archive workflow during the Job
    #       Lifecycle sprint.  Most ATS systems never permanently delete job
    #       openings because they are linked to historical applications and
    #       interviews.
    def delete_job(self, job_id: str) -> None:
        """Permanently delete a Job Opening record.

        Performs a safe delete — if Frappe detects linked records that
        prevent deletion (e.g. Job Applications), an ``ATSConflictError``
        is raised with a user-friendly message instead of exposing the raw
        Frappe exception.

        Parameters
        ----------
        job_id : str
            The ``name`` of the Job Opening to delete.

        Raises
        ------
        ATSValidationError
            If ``job_id`` is empty.
        ATSNotFoundError
            If no Job Opening with the given ID exists.
        ATSConflictError
            If the Job Opening has linked records that prevent deletion.

        TODO: Replace hard delete with archive workflow during Job Lifecycle sprint.
        TODO: Log deletion to Activity Log via ActivityLogService.
        """
        if not job_id:
            raise ATSValidationError("job_id is required.", field="job_id")

        # Confirm existence before attempting delete.
        self._get_or_raise(job_id)

        try:
            frappe.delete_doc(
                DOCTYPE_JOB_OPENING,
                job_id,
                ignore_permissions=True,
                force=False,  # Respect Frappe's link-existence checks.
            )
        except LinkExistsError as exc:
            raise ATSConflictError(
                f"Job Opening '{job_id}' cannot be deleted because it is "
                "referenced by one or more linked records (e.g. Job Applications). "
                "Please resolve those references first.",
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
        """Return a paginated, filtered list of Job Opening records.

        Parameters
        ----------
        page : int, optional
            Page number (1-indexed).  Defaults to ``DEFAULT_PAGE``.
        page_size : int, optional
            Records per page.  Capped at ``MAX_PAGE_SIZE``.
        filters : dict or None, optional
            Optional field filters.  Supported keys today:

            - ``company``          (str) — filter by Company.
            - ``department``       (str) — filter by Department.
            - ``employment_type``  (str) — filter by Employment Type.
            - ``status``           (str) — filter by Job Opening status.
            - ``location``         (str) — filter by location.

            Additional keys can be added to ``_build_filters`` without
            changing this method signature.
        order_by : str, optional
            Sort field.  Must be in ``ALLOWED_SORT_FIELDS``.
            Defaults to ``"creation"``.
        order_dir : str, optional
            Sort direction — ``"asc"`` or ``"desc"``.  Defaults to ``"desc"``.

        Returns
        -------
        dict
            ``{ "data": list[dict], "total": int, "page": int, "page_size": int }``

        TODO: Add employer-scoped filtering once Employer–Company linking is defined.
        TODO: Add salary range filter in a future sprint.
        """
        page, page_size = self._sanitise_pagination(page, page_size)
        order_clause = self._sanitise_order_by(order_by, order_dir)
        orm_filters = self._build_filters(filters or {})

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
        """Search Job Openings across ``SEARCHABLE_FIELDS`` using a single query string.

        Generates an ``OR`` filter across all fields defined in
        ``SEARCHABLE_FIELDS``.  To add a new field to the search scope,
        append it to ``SEARCHABLE_FIELDS`` — no other code changes are needed.

        The search term is lowercased before building the ``LIKE`` filters.
        MariaDB's default collation (``utf8mb4_general_ci``) is already
        case-insensitive; this is a belt-and-suspenders measure for ``_bin``
        collation environments.

        Parameters
        ----------
        search : str
            The search term.  Lowercased and wrapped with ``%`` wildcards
            for case-insensitive partial matching.
        page : int, optional
            Page number (1-indexed).
        page_size : int, optional
            Records per page.  Capped at ``MAX_PAGE_SIZE``.
        filters : dict or None, optional
            Additional field filters applied alongside the search
            (same keys as ``list_jobs``).
        order_by : str, optional
            Sort field.  Must be in ``ALLOWED_SORT_FIELDS``.
        order_dir : str, optional
            Sort direction.  Defaults to ``"desc"``.

        Returns
        -------
        dict
            ``{ "data": list[dict], "total": int, "page": int, "page_size": int }``

        TODO: Upgrade to full-text search index once data volume warrants it.
        """
        if not search or not search.strip():
            raise ATSValidationError("Search term is required.", field="search")

        page, page_size = self._sanitise_pagination(page, page_size)
        order_clause = self._sanitise_order_by(order_by, order_dir)
        orm_filters = self._build_filters(filters or {})

        # Escape wildcard characters (% and _) to prevent search injection.
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
        """Fetch a Job Opening document or raise ``ATSNotFoundError``.

        Parameters
        ----------
        job_id : str
            The Job Opening record name.

        Returns
        -------
        frappe.Document
            The live Frappe Document object.

        Raises
        ------
        ATSNotFoundError
            If the record does not exist.
        """
        if not frappe.db.exists(DOCTYPE_JOB_OPENING, job_id):
            raise ATSNotFoundError(
                f"Job Opening '{job_id}' was not found.",
                doctype=DOCTYPE_JOB_OPENING,
                name=job_id,
            )
        return frappe.get_doc(DOCTYPE_JOB_OPENING, job_id)

    def _assert_job_code_unique(self, job_code: str) -> None:
        """Raise ``ATSConflictError`` if a Job Opening with this job_code already exists.

        Parameters
        ----------
        job_code : str
            The job code to check for uniqueness.

        Raises
        ------
        ATSConflictError
            If the job code is already in use by an existing Job Opening.
        """
        if frappe.db.exists(DOCTYPE_JOB_OPENING, {"job_code": job_code}):
            raise ATSConflictError(
                f"A Job Opening with job_code '{job_code}' already exists.",
                details={"field": "job_code", "value": job_code},
            )

    @staticmethod
    def _generate_job_code() -> str:
        """Generate a unique job_code for draft/job creation if missing."""
        try:
            from frappe.model.naming import make_autoname
            return make_autoname("JOB-.#####")
        except Exception:
            import uuid
            return f"JOB-{uuid.uuid4().hex[:8].upper()}"

    @staticmethod
    def _get_default_company() -> str:
        """Resolve the company name from the current authenticated employer user."""
        from recruitrain_employer.utils.permissions import get_current_company
        return get_current_company()

    def publish_job(self, job_id: str, data: dict | None = None) -> dict:
        """Publish a Job Opening, enforcing strict publish validation."""
        if not job_id:
            raise ATSValidationError("job_id is required.", field="job_id")
        doc = self._get_or_raise(job_id)

        if data:
            normalize_job_payload(data)
            self._apply_changed_fields(doc, data)

        from recruitrain_employer.utils.permissions import get_current_company
        current_company = get_current_company()
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
        }
        self._validator.validate_publish(combined_payload)

        if combined_payload.get("employment_type"):
            doc.employment_type = combined_payload["employment_type"]

        doc.published = 1
        doc.status = "Open"
        doc.save(ignore_permissions=True)
        self._notify(
            title="Job Opening Published",
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
        """Calculate aggregated ATS summary metrics for a list of Job Opening IDs in batch.

        Avoids N+1 query overhead by grouping counts across Job Application,
        Interview, and Offer records in 3 aggregated DB queries.
        """
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
        """Serialise a Frappe Job Opening Document to a plain, JSON-safe dict enriched with ATS summary metrics."""
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

        # Frontend contract aliases
        if "job_summary" in data and "description" not in data:
            data["description"] = data["job_summary"]
        if "minimum_salary" in data and "salary_min" not in data:
            data["salary_min"] = data["minimum_salary"]
        if "maximum_salary" in data and "salary_max" not in data:
            data["salary_max"] = data["maximum_salary"]
        if "number_of_openings" in data and "number_of_positions" not in data:
            data["number_of_positions"] = data["number_of_openings"]

        # Synthetic location display string
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
        """Apply only genuinely changed fields onto a Frappe Document object."""
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
        """Construct a Frappe ORM filter dict using strictly valid DocType schema fields.

        Supported Filter Keys
        ---------------------
        - ``company``          (str) — filter by Company.
        - ``department``       (str) — filter by Department.
        - ``profession``       (str) — filter by Profession.
        - ``employment_type``  (str) — filter by Employment Type.
        - ``industry``         (str) — filter by Industry.
        - ``status``           (str) — filter by Job Opening status.
        - ``city``             (str) — filter by City.
        - ``state``            (str) — filter by State.
        - ``country``          (str) — filter by Country.
        - ``remote``           (int/bool) — filter remote.
        - ``hybrid``           (int/bool) — filter hybrid.
        - ``published``        (int/bool) — filter published status.
        - ``featured_job``     (int/bool) — filter featured status.
        - ``location``         (str) — searched via city column.
        """
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
        """Clamp page and page_size to safe, valid ranges.

        Parameters
        ----------
        page : int
            Requested page number (user-supplied — never trust raw input).
        page_size : int
            Requested records per page (capped at ``MAX_PAGE_SIZE``).

        Returns
        -------
        tuple[int, int]
            Validated ``(page, page_size)`` pair.
        """
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
        return page, page_size

    @staticmethod
    def _sanitise_order_by(order_by: str, order_dir: str) -> str:
        """Return a validated ``ORDER BY`` clause string for ``frappe.get_list``.

        Rejects any ``order_by`` value not present in ``ALLOWED_SORT_FIELDS``
        and falls back to ``creation desc`` to prevent malformed queries.

        Parameters
        ----------
        order_by : str
            Requested sort field.
        order_dir : str
            Requested sort direction (``"asc"`` or ``"desc"``).

        Returns
        -------
        str
            A safe ``"field direction"`` string, e.g. ``"job_title asc"``.
        """
        safe_field = order_by if order_by in ALLOWED_SORT_FIELDS else "creation"
        safe_dir = "asc" if str(order_dir).lower() == "asc" else "desc"
        return f"{safe_field} {safe_dir}"
