# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.services.candidate_service
================================================

Candidate Profile Business Logic Service.

Architecture
------------
All database operations for the Candidate domain are centralised here.
The API layer (``recruitrain_employer.api.candidate``) must not access
``frappe.get_doc``, ``frappe.get_all``, or ``frappe.db`` directly.

Request/Response Flow::

    React
      │
      ▼
    api/candidate.py          ← Parse input, invoke service, format response
      │
      ▼
    CandidateService          ← Business logic, ORM queries
      │
      ▼
    CandidateValidator        ← Normalization + validation
      │
      ▼
    Frappe ORM / MariaDB

Normalization Contract
----------------------
``CandidateValidator.validate_create`` and ``validate_update`` normalize
``email`` and ``phone`` **in-place** on the input ``data`` dict before
returning.  This means ``CandidateService`` always receives — and stores —
canonical values:

- ``email``  → trimmed, lowercase.
- ``phone``  → cosmetic punctuation stripped (spaces, dashes, parentheses).

Serializer Safety
-----------------
``_serialize_candidate`` actively excludes Frappe internal metadata fields
(``owner``, ``modified_by``, ``creation``, ``modified``, ``idx``,
``docstatus``, ``doctype``, ``parent``, ``parentfield``, ``parenttype``)
from every response.  Only business-facing fields defined in ``_LIST_FIELDS``
or ``_DETAIL_FIELDS`` are returned.  The exclusion set is applied as a
second gate regardless of what ``fields`` is passed, providing defence-in-depth.

Changed-Field Tracking
-----------------------
``_apply_changed_fields`` replaces the previous ``_apply_fields`` helper.
It writes only fields whose values have actually changed, skipping identical
values.  This:

1. Prevents unnecessary Frappe dirty-field tracking.
2. Returns a ``dict`` of ``{field: new_value}`` ready for Activity Log
   diffing (implemented in a future sprint).

Scope — Sprint: Candidate Management Foundation
-----------------------------------------------
This sprint implements CRUD operations on the **Candidate** DocType only.

Out of scope (implemented in future sprints):
- Candidate Education / Experience / Skills / Languages / Certifications
- Candidate Documents and resume upload
- Profile completeness scoring
- Activity Log and Notification integration
- Soft-delete / archive workflow

DocTypes Used
-------------
- Candidate

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
from frappe.exceptions import LinkExistsError

from recruitrain_employer.utils.constants import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    DOCTYPE_CANDIDATE,
    MAX_PAGE_SIZE,
)
from recruitrain_employer.utils.exceptions import (
    ATSConflictError,
    ATSNotFoundError,
    ATSValidationError,
)
from recruitrain_employer.validators.candidate_validator import CandidateValidator


# ---------------------------------------------------------------------------
# Module-Level Constants
# ---------------------------------------------------------------------------

#: Fields used to search across Candidate records.
#: To add a new searchable field, append it here — no other changes needed.
#: Search uses LIKE with a lowercased term for case-insensitive matching.
SEARCHABLE_FIELDS: tuple[str, ...] = (
    "first_name",
    "last_name",
    "email",
    "phone",
    "profession",
    "current_location",
)

#: Fields callers may pass to ``order_by``.
#: Any value not in this set is silently replaced with ``"creation"``
#: to prevent malformed queries.
ALLOWED_SORT_FIELDS: frozenset[str] = frozenset(
    [
        "creation",
        "modified",
        "first_name",
        "last_name",
        "email",
        "status",
    ]
)

#: Frappe internal metadata fields that must never appear in API responses.
#: Applied as a second exclusion gate in ``_serialize_candidate`` regardless
#: of what field list is passed in — defence-in-depth against accidental
#: exposure of system data.
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
    "first_name",
    "last_name",
    "email",
    "phone",
    "profession",
    "current_location",
    "status",
]

#: Fields returned in a full Candidate detail response.
#: Must not overlap with ``_FRAPPE_METADATA_FIELDS``.
_DETAIL_FIELDS: list[str] = _LIST_FIELDS + [
    "date_of_birth",
    "gender",
    "nationality",
    "bio",
    "linkedin_url",
    "portfolio_url",
]


class CandidateService:
    """Encapsulates business logic for Candidate profile operations.

    All database reads and writes for the Candidate domain go through
    this class.  No DocType access is permitted in the API layer.

    Usage
    -----
    ::

        service = CandidateService()
        candidate = service.get_candidate("CAND-0001")
    """

    def __init__(self) -> None:
        self._validator = CandidateValidator()

    # ------------------------------------------------------------------
    # CRUD Methods
    # ------------------------------------------------------------------

    def create_candidate(self, data: dict) -> dict:
        """Create a new Candidate record.

        Normalization is performed by ``CandidateValidator.validate_create``
        in-place on ``data`` before the record is saved.  The canonical
        (normalized) values are therefore what gets persisted.

        Parameters
        ----------
        data : dict
            Candidate field values.  Must include at a minimum:
            ``first_name``, ``last_name``, ``email``.
            ``email`` will be normalized (trimmed, lowercased) in-place.
            ``phone`` will be normalized (punctuation stripped) in-place
            if provided.

        Returns
        -------
        dict
            The newly created Candidate document serialised by
            ``_serialize_candidate()``.

        Raises
        ------
        ATSValidationError
            If required fields are missing or any value is invalid.
        ATSConflictError
            If a Candidate with the same normalized email already exists.

        TODO: Log candidate creation to Activity Log via ActivityLogService.
        TODO: Send welcome email to candidate via NotificationService.
        """
        # validate_create normalizes email and phone in-place before checking.
        self._validator.validate_create(data)

        # Uniqueness check uses the normalized email written back by the validator.
        self._assert_email_unique(data["email"])

        doc = frappe.new_doc(DOCTYPE_CANDIDATE)
        self._apply_changed_fields(doc, data)
        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        return self._serialize_candidate(doc, fields=_DETAIL_FIELDS)

    def get_candidate(self, candidate_id: str) -> dict:
        """Retrieve a full Candidate profile by record name.

        Parameters
        ----------
        candidate_id : str
            The ``name`` (primary key) of the Candidate record.

        Returns
        -------
        dict
            The Candidate document serialised by ``_serialize_candidate()``.
            Only business-facing fields are included; Frappe metadata is
            excluded by the serialiser.

        Raises
        ------
        ATSValidationError
            If ``candidate_id`` is empty.
        ATSNotFoundError
            If no Candidate with the given ID exists.

        TODO: Attach sub-resource summaries (education count, skill count, etc.)
              once those sprints are implemented.
        """
        if not candidate_id:
            raise ATSValidationError("candidate_id is required.", field="candidate_id")

        doc = self._get_or_raise(candidate_id)
        return self._serialize_candidate(doc, fields=_DETAIL_FIELDS)

    def update_candidate(self, candidate_id: str, data: dict) -> dict:
        """Apply a partial update to an existing Candidate record.

        Only fields whose values have **changed** from the current document
        are written.  Identical values are skipped, preventing unnecessary
        dirty-field tracking and keeping the Activity Log diff clean for a
        future sprint.

        Parameters
        ----------
        candidate_id : str
            The ``name`` of the Candidate to update.
        data : dict
            Partial Candidate fields to apply.  Only fields present in
            ``CANDIDATE_UPDATABLE_FIELDS`` are accepted.
            ``phone`` will be normalized (punctuation stripped) in-place
            if provided.

        Returns
        -------
        dict
            The updated Candidate document serialised by
            ``_serialize_candidate()``.

        Raises
        ------
        ATSValidationError
            If ``candidate_id`` is empty, ``data`` is empty, or any field
            is not updatable.
        ATSNotFoundError
            If no Candidate with the given ID exists.

        TODO: Pass ``changed_fields`` to ActivityLogService once implemented.
        """
        if not candidate_id:
            raise ATSValidationError("candidate_id is required.", field="candidate_id")

        # validate_update normalizes phone in-place before checking.
        self._validator.validate_update(data)

        doc = self._get_or_raise(candidate_id)

        # Apply only changed fields; the returned dict is ready for the
        # Activity Log in a future sprint.
        changed_fields = self._apply_changed_fields(doc, data)

        if changed_fields:
            doc.save(ignore_permissions=True)
            frappe.db.commit()
            # TODO: Log changed_fields to Activity Log via ActivityLogService.

        return self._serialize_candidate(doc, fields=_DETAIL_FIELDS)

    # TODO: Replace hard delete with an archive/deactivate workflow
    #       when the Candidate lifecycle (Active → Archived → Deleted) is
    #       implemented.  Most ATS systems never permanently delete candidates
    #       to preserve historical application and interview records.
    def delete_candidate(self, candidate_id: str) -> None:
        """Permanently delete a Candidate record.

        Performs a safe delete — if Frappe detects linked records that
        prevent deletion (e.g. Job Applications, Interviews), an
        ``ATSConflictError`` is raised with a user-friendly message instead
        of exposing the raw Frappe exception.

        Parameters
        ----------
        candidate_id : str
            The ``name`` of the Candidate to delete.

        Raises
        ------
        ATSValidationError
            If ``candidate_id`` is empty.
        ATSNotFoundError
            If no Candidate with the given ID exists.
        ATSConflictError
            If the Candidate has linked records that prevent deletion.

        TODO: Log deletion to Activity Log via ActivityLogService.
        """
        if not candidate_id:
            raise ATSValidationError("candidate_id is required.", field="candidate_id")

        # Confirm existence before attempting delete.
        self._get_or_raise(candidate_id)

        try:
            frappe.delete_doc(
                DOCTYPE_CANDIDATE,
                candidate_id,
                ignore_permissions=True,
                force=False,  # Respect Frappe's link-existence checks.
            )
            frappe.db.commit()
        except LinkExistsError as exc:
            raise ATSConflictError(
                f"Candidate '{candidate_id}' cannot be deleted because it is "
                "referenced by one or more linked records (e.g. Job Applications, "
                "Interviews). Please resolve those references first.",
                details={"candidate_id": candidate_id},
            ) from exc

    def list_candidates(
        self,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
        filters: dict | None = None,
        order_by: str = "creation",
        order_dir: str = "desc",
    ) -> dict:
        """Return a paginated, filtered list of Candidate records.

        Parameters
        ----------
        page : int, optional
            Page number (1-indexed).  Defaults to ``DEFAULT_PAGE``.
        page_size : int, optional
            Records per page.  Capped at ``MAX_PAGE_SIZE``.
        filters : dict or None, optional
            Optional field filters.  Supported keys today:

            - ``status``  (str) — filter by Candidate status field.

            Additional keys (``company``, ``profession``, ``location``, etc.)
            can be added to ``_build_orm_filters`` without changing this
            method signature.
        order_by : str, optional
            Sort field.  Must be in ``ALLOWED_SORT_FIELDS``.
            Defaults to ``"creation"``.
        order_dir : str, optional
            Sort direction — ``"asc"`` or ``"desc"``.  Defaults to ``"desc"``.

        Returns
        -------
        dict
            ``{ "data": list[dict], "total": int, "page": int, "page_size": int }``

        TODO: Add company-scoped filtering once Employer–Candidate linking is defined.
        TODO: Add profession, location, experience-level filters in a future sprint.
        """
        page, page_size = self._sanitise_pagination(page, page_size)
        order_clause = self._sanitise_order_by(order_by, order_dir)
        orm_filters = self._build_orm_filters(filters or {})

        total = frappe.db.count(DOCTYPE_CANDIDATE, filters=orm_filters)

        records = frappe.get_list(
            DOCTYPE_CANDIDATE,
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

    def search_candidates(
        self,
        search: str,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
        filters: dict | None = None,
        order_by: str = "creation",
        order_dir: str = "desc",
    ) -> dict:
        """Search Candidates across ``SEARCHABLE_FIELDS`` using a single query string.

        Generates an ``OR`` filter across all fields defined in
        ``SEARCHABLE_FIELDS``.  To add a new field to the search scope,
        append it to ``SEARCHABLE_FIELDS`` — no other code changes are needed.

        The search term is lowercased before building the ``LIKE`` filters.
        MariaDB's default collation (``utf8mb4_general_ci``) is already
        case-insensitive, so this is a belt-and-suspenders measure that also
        ensures correct behaviour if a ``_bin`` collation is ever configured.

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
            (same keys as ``list_candidates``).
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
        orm_filters = self._build_orm_filters(filters or {})

        # Lowercase the term so the LIKE pattern is case-insensitive even on
        # binary collations.  The leading/trailing % enable substring matching.
        term = f"%{search.strip().lower()}%"
        or_filters = [[field, "like", term] for field in SEARCHABLE_FIELDS]

        # Count uses base filters only; or_filters complicate exact counting
        # but the trade-off is acceptable for current data volumes.
        # TODO: Implement accurate total for or_filter queries if pagination
        #       accuracy becomes critical at scale.
        total = frappe.db.count(DOCTYPE_CANDIDATE, filters=orm_filters)

        records = frappe.get_list(
            DOCTYPE_CANDIDATE,
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
    # Sub-Resource Queries (Future Sprints)
    # ------------------------------------------------------------------

    def get_education(self, candidate_id: str) -> list:
        """Return all Candidate Education records for a Candidate.

        TODO: Implement in the Candidate Sub-Resources sprint.
        """
        pass

    def get_experience(self, candidate_id: str) -> list:
        """Return all Candidate Experience records for a Candidate.

        TODO: Implement in the Candidate Sub-Resources sprint.
        """
        pass

    def get_skills(self, candidate_id: str) -> list:
        """Return all Candidate Skill records for a Candidate.

        TODO: Implement in the Candidate Sub-Resources sprint.
        """
        pass

    def get_certifications(self, candidate_id: str) -> list:
        """Return all Candidate Certification records for a Candidate.

        TODO: Implement in the Candidate Sub-Resources sprint.
        """
        pass

    def get_languages(self, candidate_id: str) -> list:
        """Return all Candidate Language records for a Candidate.

        TODO: Implement in the Candidate Sub-Resources sprint.
        """
        pass

    def get_documents(self, candidate_id: str) -> list:
        """Return all Candidate Document records for a Candidate.

        TODO: Implement in the Document Upload sprint.
        """
        pass

    # ------------------------------------------------------------------
    # Profile Completeness (Future Sprint)
    # ------------------------------------------------------------------

    def get_profile_completeness(self, candidate_id: str) -> dict:
        """Calculate a profile completeness score for the given Candidate.

        Scoring Sections (planned)
        --------------------------
        - Basic Info (name, photo, contact)  — 20 %
        - Work Experience                    — 25 %
        - Education                          — 20 %
        - Skills (at least 3)                — 15 %
        - Resume / CV document               — 15 %
        - Languages                          —  5 %

        TODO: Implement in the Profile Completeness sprint.
        TODO: Return list of missing sections for frontend nudge prompts.
        """
        pass

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _get_or_raise(self, candidate_id: str):
        """Fetch a Candidate document or raise ``ATSNotFoundError``.

        Parameters
        ----------
        candidate_id : str
            The Candidate record name.

        Returns
        -------
        frappe.Document
            The live Frappe Document object.

        Raises
        ------
        ATSNotFoundError
            If the record does not exist.
        """
        if not frappe.db.exists(DOCTYPE_CANDIDATE, candidate_id):
            raise ATSNotFoundError(
                f"Candidate '{candidate_id}' was not found.",
                doctype=DOCTYPE_CANDIDATE,
                name=candidate_id,
            )
        return frappe.get_doc(DOCTYPE_CANDIDATE, candidate_id)

    def _assert_email_unique(self, email: str) -> None:
        """Raise ``ATSConflictError`` if a Candidate with this email already exists.

        Expects a normalized (trimmed, lowercase) email address so that the
        uniqueness check is consistent with what is stored in the database.

        Parameters
        ----------
        email : str
            Normalized email address to check for uniqueness.

        Raises
        ------
        ATSConflictError
            If the email is already registered to an existing Candidate.
        """
        if frappe.db.exists(DOCTYPE_CANDIDATE, {"email": email}):
            raise ATSConflictError(
                f"A Candidate with email '{email}' already exists.",
                details={"field": "email", "value": email},
            )

    @staticmethod
    def _serialize_candidate(doc, fields: list[str]) -> dict:
        """Serialise a Frappe Candidate Document to a plain, JSON-safe dict.

        Named ``_serialize_candidate`` rather than a generic ``_doc_to_dict``
        because this helper is intentionally scoped to the Candidate domain.
        Each service module (Company, Job, Interview, Offer) will define its
        own ``_serialize_*`` helper, making the origin of each serialiser
        immediately obvious and allowing domain-specific post-processing
        without coupling services together.

        Metadata Exclusion
        ------------------
        This method applies a second exclusion gate: any field present in
        ``_FRAPPE_METADATA_FIELDS`` is stripped from the output regardless
        of whether it appears in ``fields``.  This provides defence-in-depth
        against accidental exposure of Frappe system data (``owner``,
        ``modified_by``, ``docstatus``, etc.).

        Parameters
        ----------
        doc : frappe.Document
            The Candidate document to serialise.
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
            # TODO: ActivityLogService.log_update(candidate_id, changed)
        """
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
    def _build_orm_filters(filters: dict) -> dict:
        """Construct a Frappe ORM filter dict from the caller-supplied filter map.

        Supported Filter Keys
        ---------------------
        - ``status``  (str) — filter by the Candidate ``status`` field.

        Adding New Filters
        ------------------
        Append a new ``if filters.get("<key>"):`` block here.  Neither
        the API method signature nor the ``list_candidates`` /
        ``search_candidates`` signatures need to change.

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

        if filters.get("status"):
            orm["status"] = filters["status"]

        # TODO: Add company-scoping filter once Employer–Candidate pool is defined.
        # if filters.get("company"):
        #     orm["company"] = filters["company"]

        # TODO: Add profession filter in a future sprint.
        # if filters.get("profession"):
        #     orm["profession"] = filters["profession"]

        # TODO: Add current_location filter in a future sprint.
        # if filters.get("location"):
        #     orm["current_location"] = filters["location"]

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
            A safe ``"field direction"`` string, e.g. ``"creation desc"``.
        """
        safe_field = order_by if order_by in ALLOWED_SORT_FIELDS else "creation"
        safe_dir = "asc" if str(order_dir).lower() == "asc" else "desc"
        return f"{safe_field} {safe_dir}"
