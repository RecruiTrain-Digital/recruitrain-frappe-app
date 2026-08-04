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
from recruitrain_employer.validators.job_validator import JobValidator


# ---------------------------------------------------------------------------
# Module-Level Constants
# ---------------------------------------------------------------------------

#: Fields used to search across Job Opening records.
#: To add a new searchable field, append it here — no other changes needed.
#: Search uses LIKE with a lowercased term for case-insensitive matching.
SEARCHABLE_FIELDS: tuple[str, ...] = (
    "job_title",
    "job_code",
    "department",
    "employment_type",
    "location",
    "company",
)

#: Fields callers may pass to ``order_by``.
#: Any value not in this set is silently replaced with ``"creation"``
#: to prevent malformed queries.
ALLOWED_SORT_FIELDS: frozenset[str] = frozenset(
    [
        "creation",
        "modified",
        "job_title",
        "company",
        "department",
        "employment_type",
        "location",
        "status",
        "opening_date",
        "closing_date",
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
    "employment_type",
    "location",
    "status",
    "opening_date",
    "closing_date",
    "target_joining_date",
    "minimum_salary",
    "maximum_salary",
    "number_of_openings",
]

#: Fields returned in a full Job Opening detail response.
#: Must not overlap with ``_FRAPPE_METADATA_FIELDS``.
_DETAIL_FIELDS: list[str] = _LIST_FIELDS + [
    "description",
    "job_summary",
    "responsibilities",
    "requirements",
    "benefits",
    "salary_min",
    "salary_max",
    "currency",
    "number_of_positions",
    "country",
    "state",
    "city",
    "remote",
    "hybrid",
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

    # ------------------------------------------------------------------
    # CRUD Methods
    # ------------------------------------------------------------------

    def create_job(self, data: dict) -> dict:
        """Create a new Job Opening record.

        Parameters
        ----------
        data : dict
            Job Opening field values.  Must include at a minimum the fields
            listed in ``JOB_REQUIRED_FIELDS`` (``job_title``, ``company``,
            ``employment_type``, ``description``).

        Returns
        -------
        dict
            The newly created Job Opening document serialised by
            ``_serialize_job()``.

        Raises
        ------
        ATSValidationError
            If required fields are missing or any value is invalid.
        ATSConflictError
            If a Job Opening with the same ``job_code`` already exists
            (when ``job_code`` is provided).

        TODO: Log job creation to Activity Log via ActivityLogService.
        TODO: Notify relevant users via NotificationService.
        """
        self._validator.validate_create(data)

        if data.get("job_code"):
            self._assert_job_code_unique(data["job_code"])

        doc = frappe.new_doc(DOCTYPE_JOB_OPENING)
        self._apply_changed_fields(doc, data)
        try:
            doc.insert(ignore_permissions=True)
        except DuplicateEntryError as exc:
            raise ATSConflictError(
                f"A Job Opening with job_code '{data.get('job_code')}' already exists.",
                details={"field": "job_code", "value": data.get("job_code")},
            ) from exc

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
        return self._serialize_job(doc, fields=_DETAIL_FIELDS)

    def update_job(self, job_id: str, data: dict) -> dict:
        """Apply a partial update to an existing Job Opening record.

        Only fields whose values have **changed** from the current document
        are written.  Identical values are skipped, preventing unnecessary
        dirty-field tracking.

        Parameters
        ----------
        job_id : str
            The ``name`` of the Job Opening to update.
        data : dict
            Partial Job Opening fields to apply.  Only fields present in
            ``JOB_UPDATABLE_FIELDS`` are accepted.

        Returns
        -------
        dict
            The updated Job Opening document serialised by ``_serialize_job()``.

        Raises
        ------
        ATSValidationError
            If ``job_id`` is empty, ``data`` is empty, or any field
            is not updatable.
        ATSNotFoundError
            If no Job Opening with the given ID exists.

        TODO: Pass ``changed_fields`` to ActivityLogService once implemented.
        """
        if not job_id:
            raise ATSValidationError("job_id is required.", field="job_id")

        self._validator.validate_update(data)

        doc = self._get_or_raise(job_id)

        # Apply only changed fields; the returned dict is ready for the
        # Activity Log in a future sprint.
        changed_fields = self._apply_changed_fields(doc, data)

        if changed_fields:
            try:
                doc.save(ignore_permissions=True)
            except DuplicateEntryError as exc:
                raise ATSConflictError(
                    f"Job Opening conflict during update.",
                    details={"job_id": job_id},
                ) from exc
            # TODO: Log changed_fields to Activity Log via ActivityLogService.

        return self._serialize_job(doc, fields=_DETAIL_FIELDS)

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

        return {
            "data": [dict(r) for r in records],
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

        return {
            "data": [dict(r) for r in records],
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
    def _serialize_job(doc, fields: list[str]) -> dict:
        """Serialise a Frappe Job Opening Document to a plain, JSON-safe dict.

        Named ``_serialize_job`` rather than a generic ``_doc_to_dict`` because
        this helper is intentionally scoped to the Job Opening domain.  Each
        service module defines its own ``_serialize_*`` helper, making the origin
        immediately obvious and allowing domain-specific post-processing without
        coupling services together.

        Metadata Exclusion
        ------------------
        This method applies a second exclusion gate: any field present in
        ``_FRAPPE_METADATA_FIELDS`` is stripped from the output regardless of
        whether it appears in ``fields``.  This provides defence-in-depth against
        accidental exposure of Frappe system data.

        Parameters
        ----------
        doc : frappe.Document
            The Job Opening document to serialise.
        fields : list[str]
            The business-facing field names to include in the output dict.

        Returns
        -------
        dict
            A plain Python dict containing only non-metadata fields whose names
            appear in ``fields``.
        """
        return {
            field: doc.get(field)
            for field in fields
            if field not in _FRAPPE_METADATA_FIELDS
        }

    @staticmethod
    def _apply_changed_fields(doc, data: dict) -> dict:
        """Apply only genuinely changed fields onto a Frappe Document object.

        Compares each incoming value against the current document value and
        only calls ``setattr`` when they differ.  This prevents Frappe from
        tracking unnecessary dirty fields and keeps the returned change dict
        clean for future Activity Log diffing.

        Parameters
        ----------
        doc : frappe.Document
            The document to mutate in-place.
        data : dict
            Field/value pairs to potentially apply.

        Returns
        -------
        dict
            A ``{field: new_value}`` dict containing only the fields that
            were actually changed.  An empty dict means no fields changed.

        Notes
        -----
        Unknown fields (not present as attributes on the document) are
        silently skipped to avoid attribute errors.

        The returned dict is intended for future Activity Log integration::

            changed = self._apply_changed_fields(doc, data)
            # TODO: ActivityLogService.log_update(job_id, changed)
        """
        changed: dict = {}
        meta = frappe.get_meta(doc.doctype)

        # Field aliases mapping API payload fields to DocType schema fields
        aliases = {
            "description": "job_summary",
            "salary_min": "minimum_salary",
            "salary_max": "maximum_salary",
            "number_of_positions": "number_of_openings",
        }

        normalized_data = dict(data)
        for alias, target in aliases.items():
            if alias in normalized_data and not meta.has_field(alias) and meta.has_field(target):
                normalized_data[target] = normalized_data.pop(alias)

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
        """Construct a Frappe ORM filter dict from the caller-supplied filter map.

        Supported Filter Keys
        ---------------------
        - ``company``          (str) — filter by Company.
        - ``department``       (str) — filter by Department.
        - ``employment_type``  (str) — filter by Employment Type.
        - ``status``           (str) — filter by Job Opening status.
        - ``location``         (str) — filter by location.

        Adding New Filters
        ------------------
        Append a new ``if filters.get("<key>"):`` block here.  The API method
        signatures and ``list_jobs`` / ``search_jobs`` signatures do not need
        to change.

        Parameters
        ----------
        filters : dict
            Caller-supplied key/value pairs from the API layer.

        Returns
        -------
        dict
            Frappe-compatible filter dict ready for ``frappe.get_list`` /
            ``frappe.db.count``.
        """
        orm: dict = {}

        if filters.get("company"):
            orm["company"] = filters["company"]

        if filters.get("department"):
            orm["department"] = filters["department"]

        if filters.get("employment_type"):
            orm["employment_type"] = filters["employment_type"]

        if filters.get("status"):
            orm["status"] = filters["status"]

        if filters.get("location"):
            orm["location"] = filters["location"]

        # TODO: Add salary range filter in a future sprint.
        # if filters.get("salary_min"):
        #     orm["salary_max"] = [">=", filters["salary_min"]]

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
