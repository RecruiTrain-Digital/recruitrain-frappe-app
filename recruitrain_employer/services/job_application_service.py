# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.services.job_application_service
=======================================================

Job Application Business Logic Service.

Architecture
------------
All database operations for the Job Application domain are centralised here.
The API layer (``recruitrain_employer.api.job_application``) must not access
``frappe.get_doc``, ``frappe.get_all``, or ``frappe.db`` directly.

Request/Response Flow::

    React
      │
      ▼
    api/job_application.py        ← Parse input, invoke service, format response
      │
      ▼
    JobApplicationService         ← Business logic, ORM queries
      │
      ▼
    JobApplicationValidator       ← Input validation
      │
      ▼
    Frappe ORM / MariaDB

Serializer Safety
-----------------
``_serialize_application`` actively excludes Frappe internal metadata fields
(``owner``, ``modified_by``, ``creation``, ``modified``, ``idx``,
``docstatus``, ``doctype``, ``parent``, ``parentfield``, ``parenttype``)
from every response.  Only business-facing fields defined in ``_LIST_FIELDS``
or ``_DETAIL_FIELDS`` are returned.

Changed-Field Tracking
-----------------------
``_apply_changed_fields`` writes only fields whose values have actually
changed, skipping identical values.  This prevents unnecessary Frappe
dirty-field tracking and returns a ``dict`` ready for Activity Log diffing
in a future sprint.

Duplicate Application Guard
---------------------------
``_assert_unique_application`` enforces the business rule that only one
active application may exist per ``(candidate, job_opening)`` pair.
On violation it raises ``ATSConflictError`` (not ``ATSValidationError``),
because a duplicate is a state conflict rather than a malformed input.

Scope — Sprint: Job Application Management Foundation
------------------------------------------------------
This sprint implements CRUD, listing, searching, and application status
management for Job Applications.

Out of scope (implemented in future sprints):
- Interview creation / scheduling
- Offer generation
- Candidate scoring / resume parsing
- Email notifications
- Pipeline Kanban / drag-and-drop
- Recruiter assignment
- Workflow engine / forward-only transition rules
- Permissions / company-scoped access control
- Activity Log implementation
- Analytics / Dashboard

DocTypes Used
-------------
- Job Application
- Candidate   (existence check in validator)
- Job Opening  (existence check in validator)

Frappe APIs Used
----------------
- ``frappe.new_doc()``       — new document instantiation
- ``frappe.get_doc()``       — single-record fetch and mutation
- ``frappe.get_list()``      — paginated, filtered listing
- ``frappe.db.exists()``     — lightweight existence check
- ``frappe.db.count()``      — total-row count for pagination
- ``frappe.db.set_value()``  — atomic single-field update for status change
- ``frappe.delete_doc()``    — safe record deletion
"""

from __future__ import annotations

import frappe
from frappe.exceptions import DuplicateEntryError, LinkExistsError

from recruitrain_employer.utils.constants import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    DOCTYPE_JOB_APPLICATION,
    MAX_PAGE_SIZE,
)
from recruitrain_employer.utils.exceptions import (
    ATSConflictError,
    ATSNotFoundError,
    ATSValidationError,
)
from recruitrain_employer.validators.job_application_validator import (
    ALLOWED_APPLICATION_STATUSES,
    JobApplicationValidator,
)


# ---------------------------------------------------------------------------
# Module-Level Constants
# ---------------------------------------------------------------------------

#: Fields used to search across Job Application records.
#: To add a new searchable field, append it here — no other changes needed.
#: Search uses LIKE with a lowercased term for case-insensitive matching.
SEARCHABLE_FIELDS: tuple[str, ...] = (
    "candidate",
    "job_opening",
    "name",
    "status",
    "company",
)

#: Fields callers may pass to ``order_by``.
#: Any value not in this set is silently replaced with ``"creation"``
#: to prevent malformed queries.
ALLOWED_SORT_FIELDS: frozenset[str] = frozenset(
    [
        "creation",
        "modified",
        "candidate",
        "job_opening",
        "company",
        "status",
        "application_date",
        "applied_on",
    ]
)

#: Frappe internal metadata fields that must never appear in API responses.
#: Applied as a second exclusion gate in ``_serialize_application`` —
#: defence-in-depth against accidental exposure of system data.
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
    "candidate",
    "job_opening",
    "company",
    "status",
    "current_stage",
    "application_date",
    "applied_on",
]

#: Fields returned in a full Job Application detail response.
#: Must not overlap with ``_FRAPPE_METADATA_FIELDS``.
_DETAIL_FIELDS: list[str] = _LIST_FIELDS + [
    "cover_letter",
    "resume",
    "notes",
    "rejection_reason",
    "source",
    "rating",
    "priority",
    "assigned_recruiter",
]


class JobApplicationService:
    """Encapsulates business logic for Job Application operations.

    All database reads and writes for the Job Application domain go through
    this class.  No DocType access is permitted in the API layer.

    Usage
    -----
    ::

        service = JobApplicationService()
        application = service.get_application("APP-0001")
    """

    def __init__(self) -> None:
        self._validator = JobApplicationValidator()

    # ------------------------------------------------------------------
    # CRUD Methods
    # ------------------------------------------------------------------

    def create_application(self, data: dict) -> dict:
        """Submit a new Job Application.

        Parameters
        ----------
        data : dict
            Job Application field values.  Must include at a minimum
            ``job_opening`` and ``candidate``.

        Returns
        -------
        dict
            The newly created Job Application document serialised by
            ``_serialize_application()``.

        Raises
        ------
        ATSValidationError
            If required fields are missing or any linked record does not exist.
        ATSConflictError
            If a Job Application for the same ``(candidate, job_opening)``
            pair already exists.

        TODO: Log application creation to Activity Log via ActivityLogService.
        TODO: Notify employer team of new application via NotificationService.
        """
        self._validator.validate_create(data)
        self._assert_unique_application(data["candidate"], data["job_opening"])

        doc = frappe.new_doc(DOCTYPE_JOB_APPLICATION)
        self._apply_changed_fields(doc, data)
        try:
            doc.insert(ignore_permissions=True)
        except DuplicateEntryError as exc:
            raise ATSConflictError(
                f"A Job Application for candidate '{data.get('candidate')}' and job opening '{data.get('job_opening')}' already exists.",
                details={"candidate": data.get("candidate"), "job_opening": data.get("job_opening")},
            ) from exc

        return self._serialize_application(doc, fields=_DETAIL_FIELDS)

    def get_application(self, application_id: str) -> dict:
        """Retrieve a full Job Application record by ID.

        Parameters
        ----------
        application_id : str
            The ``name`` (primary key) of the Job Application record.

        Returns
        -------
        dict
            The Job Application document serialised by
            ``_serialize_application()``.  Only business-facing fields are
            included; Frappe metadata is excluded by the serialiser.

        Raises
        ------
        ATSValidationError
            If ``application_id`` is empty.
        ATSNotFoundError
            If no Job Application with the given ID exists.

        TODO: Attach interview history once Interview sprint is implemented.
        TODO: Attach candidate snapshot (name, email, phone) for convenience.
        """
        if not application_id:
            raise ATSValidationError(
                "application_id is required.", field="application_id"
            )

        doc = self._get_or_raise(application_id)
        return self._serialize_application(doc, fields=_DETAIL_FIELDS)

    def update_application(self, application_id: str, data: dict) -> dict:
        """Apply a partial update to an existing Job Application record.

        Only fields whose values have **changed** from the current document
        are written.  Identical values are skipped, preventing unnecessary
        dirty-field tracking.

        Parameters
        ----------
        application_id : str
            The ``name`` of the Job Application to update.
        data : dict
            Partial Job Application fields to apply.  Only fields in
            ``APPLICATION_UPDATABLE_FIELDS`` are accepted.
            ``candidate`` and ``job_opening`` are immutable after creation.

        Returns
        -------
        dict
            The updated Job Application document serialised by
            ``_serialize_application()``.

        Raises
        ------
        ATSValidationError
            If ``application_id`` is empty, ``data`` is empty, or any field
            is not updatable.
        ATSNotFoundError
            If no Job Application with the given ID exists.

        TODO: Pass ``changed_fields`` to ActivityLogService once implemented.
        """
        if not application_id:
            raise ATSValidationError(
                "application_id is required.", field="application_id"
            )

        self._validator.validate_update(data)

        doc = self._get_or_raise(application_id)

        # Apply only changed fields; the returned dict is ready for the
        # Activity Log in a future sprint.
        changed_fields = self._apply_changed_fields(doc, data)

        if changed_fields:
            try:
                doc.save(ignore_permissions=True)
            except DuplicateEntryError as exc:
                raise ATSConflictError(
                    f"Job Application conflict during update.",
                    details={"application_id": application_id},
                ) from exc
            # TODO: Log changed_fields to Activity Log via ActivityLogService.

        return self._serialize_application(doc, fields=_DETAIL_FIELDS)

    # TODO: Replace hard delete with an archive workflow during the Application
    #       Lifecycle sprint.  Most ATS systems never permanently delete
    #       applications to preserve historical records.
    def delete_application(self, application_id: str) -> None:
        """Permanently delete a Job Application record.

        Performs a safe delete — if Frappe detects linked records that
        prevent deletion, an ``ATSConflictError`` is raised with a
        user-friendly message instead of exposing the raw Frappe exception.

        Parameters
        ----------
        application_id : str
            The ``name`` of the Job Application to delete.

        Raises
        ------
        ATSValidationError
            If ``application_id`` is empty.
        ATSNotFoundError
            If no Job Application with the given ID exists.
        ATSConflictError
            If the Job Application has linked records that prevent deletion
            (e.g. Interviews, Offers).

        TODO: Replace hard delete with archive workflow in Application Lifecycle sprint.
        TODO: Log deletion to Activity Log via ActivityLogService.
        """
        if not application_id:
            raise ATSValidationError(
                "application_id is required.", field="application_id"
            )

        # Confirm existence before attempting delete.
        self._get_or_raise(application_id)

        try:
            frappe.delete_doc(
                DOCTYPE_JOB_APPLICATION,
                application_id,
                ignore_permissions=True,
                force=False,  # Respect Frappe's link-existence checks.
            )
        except LinkExistsError as exc:
            raise ATSConflictError(
                f"Job Application '{application_id}' cannot be deleted because "
                "it is referenced by one or more linked records (e.g. Interviews, "
                "Offers). Please resolve those references first.",
                details={"application_id": application_id},
            ) from exc

    def list_applications(
        self,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
        filters: dict | None = None,
        order_by: str = "creation",
        order_dir: str = "desc",
    ) -> dict:
        """Return a paginated, filtered list of Job Application records.

        Parameters
        ----------
        page : int, optional
            Page number (1-indexed).  Defaults to ``DEFAULT_PAGE``.
        page_size : int, optional
            Records per page.  Capped at ``MAX_PAGE_SIZE``.
        filters : dict or None, optional
            Optional field filters.  Supported keys today:

            - ``candidate``       (str) — filter by Candidate ID.
            - ``job_opening``     (str) — filter by Job Opening ID.
            - ``company``         (str) — filter by Company.
            - ``status``          (str) — filter by application status.
            - ``application_date`` (str) — filter by exact application date.

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
        TODO: Add date-range filtering (application_date_from, application_date_to).
        """
        page, page_size = self._sanitise_pagination(page, page_size)
        order_clause = self._sanitise_order_by(order_by, order_dir)
        orm_filters = self._build_filters(filters or {})

        total = frappe.db.count(DOCTYPE_JOB_APPLICATION, filters=orm_filters)

        records = frappe.get_list(
            DOCTYPE_JOB_APPLICATION,
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

    def search_applications(
        self,
        search: str,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
        filters: dict | None = None,
        order_by: str = "creation",
        order_dir: str = "desc",
    ) -> dict:
        """Search Job Applications across ``SEARCHABLE_FIELDS`` using a single query string.

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
            (same keys as ``list_applications``).
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

        total = frappe.db.count(DOCTYPE_JOB_APPLICATION, filters=orm_filters, or_filters=or_filters)

        records = frappe.get_list(
            DOCTYPE_JOB_APPLICATION,
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

    def change_status(self, application_id: str, new_status: str) -> dict:
        """Change the status of a Job Application atomically.

        Uses ``frappe.db.set_value`` for an atomic, single-field update rather
        than loading and saving the full document.  This is the preferred
        approach for status-only changes because it avoids triggering unrelated
        ``before_save`` hooks.

        Parameters
        ----------
        application_id : str
            The ``name`` of the Job Application to update.
        new_status : str
            The new status value.  Must be in ``ALLOWED_APPLICATION_STATUSES``.

        Returns
        -------
        dict
            The updated Job Application document serialised by
            ``_serialize_application()``.

        Raises
        ------
        ATSValidationError
            If ``application_id`` or ``new_status`` is empty, or if
            ``new_status`` is not in ``ALLOWED_APPLICATION_STATUSES``.
        ATSNotFoundError
            If no Job Application with the given ID exists.

        TODO: Enforce forward-only transition rules in the Application Lifecycle sprint.
        TODO: Block transitions from terminal stages (Hired, Rejected, Withdrawn).
        TODO: Log status change to Activity Log via ActivityLogService.
        TODO: Send status-change notification to candidate via NotificationService.
        """
        if not application_id:
            raise ATSValidationError(
                "application_id is required.", field="application_id"
            )

        if not new_status:
            raise ATSValidationError(
                "new_status is required.", field="new_status"
            )

        # Validate the status value before touching the database.
        self._validator.validate_status(new_status)

        # Confirm the application exists before updating.
        doc = self._get_or_raise(application_id)

        frappe.db.set_value(
            DOCTYPE_JOB_APPLICATION,
            application_id,
            "status",
            new_status,
            update_modified=True,
        )

        # Reload the document to reflect the committed value.
        doc.reload()
        return self._serialize_application(doc, fields=_DETAIL_FIELDS)

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _get_or_raise(self, application_id: str):
        """Fetch a Job Application document or raise ``ATSNotFoundError``.

        Parameters
        ----------
        application_id : str
            The Job Application record name.

        Returns
        -------
        frappe.Document
            The live Frappe Document object.

        Raises
        ------
        ATSNotFoundError
            If the record does not exist.
        """
        if not frappe.db.exists(DOCTYPE_JOB_APPLICATION, application_id):
            raise ATSNotFoundError(
                f"Job Application '{application_id}' was not found.",
                doctype=DOCTYPE_JOB_APPLICATION,
                name=application_id,
            )
        return frappe.get_doc(DOCTYPE_JOB_APPLICATION, application_id)

    def _assert_unique_application(
        self, candidate: str, job_opening: str
    ) -> None:
        """Raise ``ATSConflictError`` if a duplicate application already exists.

        Enforces the business rule: only one active application per
        ``(candidate, job_opening)`` pair is allowed.

        Parameters
        ----------
        candidate : str
            The Candidate record name.
        job_opening : str
            The Job Opening record name.

        Raises
        ------
        ATSConflictError
            If a Job Application for the same ``(candidate, job_opening)``
            pair already exists.
        """
        if frappe.db.exists(
            DOCTYPE_JOB_APPLICATION,
            {"candidate": candidate, "job_opening": job_opening},
        ):
            raise ATSConflictError(
                f"A Job Application for candidate '{candidate}' and job opening "
                f"'{job_opening}' already exists. "
                "Duplicate applications are not permitted.",
                details={
                    "candidate": candidate,
                    "job_opening": job_opening,
                },
            )

    @staticmethod
    def _serialize_application(doc, fields: list[str]) -> dict:
        """Serialise a Frappe Job Application Document to a plain, JSON-safe dict.

        Named ``_serialize_application`` rather than a generic ``_doc_to_dict``
        because this helper is intentionally scoped to the Job Application domain.
        Each service module defines its own ``_serialize_*`` helper, making the
        origin immediately obvious and allowing domain-specific post-processing
        without coupling services together.

        Metadata Exclusion
        ------------------
        This method applies a second exclusion gate: any field present in
        ``_FRAPPE_METADATA_FIELDS`` is stripped from the output regardless of
        whether it appears in ``fields``.  This provides defence-in-depth against
        accidental exposure of Frappe system data (``owner``, ``modified_by``,
        ``docstatus``, etc.).

        Parameters
        ----------
        doc : frappe.Document
            The Job Application document to serialise.
        fields : list[str]
            The business-facing field names to include in the output dict.

        Returns
        -------
        dict
            A plain Python dict containing only non-metadata fields whose
            names appear in ``fields``.
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
            # TODO: ActivityLogService.log_update(application_id, changed)
        """
        changed: dict = {}
        meta = frappe.get_meta(doc.doctype)

        aliases = {
            "application_date": "applied_on",
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
        - ``candidate``        (str) — filter by Candidate ID.
        - ``job_opening``      (str) — filter by Job Opening ID.
        - ``company``          (str) — filter by Company.
        - ``status``           (str) — filter by application status.
        - ``application_date`` (str) — filter by exact application date.

        Adding New Filters
        ------------------
        Append a new ``if filters.get("<key>"):`` block here.  The API method
        signatures and ``list_applications`` / ``search_applications``
        signatures do not need to change.

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

        if filters.get("candidate"):
            orm["candidate"] = filters["candidate"]

        if filters.get("job_opening"):
            orm["job_opening"] = filters["job_opening"]

        if filters.get("company"):
            orm["company"] = filters["company"]

        if filters.get("status"):
            orm["status"] = filters["status"]

        if filters.get("applied_on"):
            orm["applied_on"] = filters["applied_on"]
        elif filters.get("application_date"):
            orm["applied_on" if frappe.get_meta(DOCTYPE_JOB_APPLICATION).has_field("applied_on") else "application_date"] = filters["application_date"]

        # TODO: Add date-range filter (application_date_from / _to) in a future sprint.

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
            A safe ``"field direction"`` string, e.g. ``"application_date desc"``.
        """
        safe_field = order_by if order_by in ALLOWED_SORT_FIELDS else "creation"
        safe_dir = "asc" if str(order_dir).lower() == "asc" else "desc"
        return f"{safe_field} {safe_dir}"
