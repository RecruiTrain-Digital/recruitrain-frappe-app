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
from frappe.exceptions import DuplicateEntryError, LinkExistsError

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
#: Search uses LIKE with a lowercased term for case-insensitive matching.
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

#: Fields callers may pass to ``order_by``.
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

#: Frappe internal metadata fields that must never appear in API responses.
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
_LIST_FIELDS: list[str] = [
    "name",
    "candidate_id",
    "candidate_name",
    "first_name",
    "last_name",
    "email",
    "mobile_no",
    "current_job_title",
    "current_company",
    "profession",
    "city",
    "state",
    "country",
    "preferred_location",
    "years_of_experience",
    "status",
]

#: Fields returned in a full Candidate detail response.
_DETAIL_FIELDS: list[str] = _LIST_FIELDS + [
    "middle_name",
    "date_of_birth",
    "gender",
    "nationality",
    "marital_status",
    "alternate_mobile",
    "linkedin",
    "portfolio",
    "github",
    "notice_period",
    "current_salary",
    "expected_salary",
    "employment_type",
    "address_line_1",
    "address_line_2",
    "postal_code",
    "source",
    "resume",
    "profile_completion",
    "passport_number",
    "passport_expiry",
    "visa_status",
    "work_permit",
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
        try:
            doc.insert(ignore_permissions=True)
        except DuplicateEntryError as exc:
            raise ATSConflictError(
                f"A Candidate with email '{data.get('email')}' already exists.",
                details={"field": "email", "value": data.get("email")},
            ) from exc

        from recruitrain_employer.utils.permissions import get_current_company
        self._notify(
            title="New Candidate Added",
            message=f"Candidate profile '{doc.first_name} {doc.last_name}' ({doc.name}) was created.",
            priority="Low",
            category="Candidate",
            company=doc.get("company") or get_current_company(),
            entity_id=doc.name,
            action_url=f"/candidates/{doc.name}",
            action_label="View Candidate",
        )

        batch_apps = self._get_batch_latest_applications([doc.name])
        return self._serialize_candidate(doc, fields=_DETAIL_FIELDS, application=batch_apps.get(doc.name))


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
        batch_apps = self._get_batch_latest_applications([candidate_id])
        return self._serialize_candidate(doc, fields=_DETAIL_FIELDS, application=batch_apps.get(candidate_id))

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
            try:
                doc.save(ignore_permissions=True)
            except DuplicateEntryError as exc:
                raise ATSConflictError(
                    f"Candidate conflict during update.",
                    details={"candidate_id": candidate_id},
                ) from exc
            from recruitrain_employer.utils.permissions import get_current_company
            self._notify(
                title="Candidate Profile Updated",
                message=f"Candidate profile for {getattr(doc, 'candidate_name', doc.name)} was updated.",
                priority="Low",
                category="Candidate",
                company=getattr(doc, "company", "") or get_current_company(),
                entity_id=doc.name,
                action_url=f"/candidates/{doc.name}",
                action_label="View Candidate",
            )


        batch_apps = self._get_batch_latest_applications([candidate_id])
        return self._serialize_candidate(doc, fields=_DETAIL_FIELDS, application=batch_apps.get(candidate_id))

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

        candidate_ids = [r["name"] for r in records if "name" in r]
        batch_applications = self._get_batch_latest_applications(candidate_ids)

        return {
            "data": [
                self._serialize_candidate(
                    r, fields=_LIST_FIELDS, application=batch_applications.get(r.get("name"))
                )
                for r in records
            ],
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

        # Escape wildcard characters (% and _) to prevent search injection.
        escaped_search = search.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        term = f"%{escaped_search}%"
        or_filters = [[field, "like", term] for field in SEARCHABLE_FIELDS]

        total = frappe.db.count(DOCTYPE_CANDIDATE, filters=orm_filters, or_filters=or_filters)

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

        candidate_ids = [r["name"] for r in records if "name" in r]
        batch_applications = self._get_batch_latest_applications(candidate_ids)

        return {
            "data": [
                self._serialize_candidate(
                    r, fields=_LIST_FIELDS, application=batch_applications.get(r.get("name"))
                )
                for r in records
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    # ------------------------------------------------------------------
    # Sub-Resource Operations & International Candidate Domain
    # ------------------------------------------------------------------

    def get_education(self, candidate_id: str) -> list[dict]:
        """Return all Candidate Education records for a Candidate."""
        doc = self._get_or_raise(candidate_id)
        return self._serialize_child_table(doc.get("education") or [])

    def update_education(self, candidate_id: str, education: list) -> dict:
        """Replace all Candidate Education records for a Candidate."""
        self._validator.validate_education(education)
        doc = self._get_or_raise(candidate_id)
        doc.set("education", education)
        doc.save(ignore_permissions=True)
        return self.get_candidate(candidate_id)

    def get_experience(self, candidate_id: str) -> list[dict]:
        """Return all Candidate Experience records for a Candidate."""
        doc = self._get_or_raise(candidate_id)
        return self._serialize_child_table(doc.get("experience") or [])

    def update_experience(self, candidate_id: str, experience: list) -> dict:
        """Replace all Candidate Experience records for a Candidate."""
        self._validator.validate_experience(experience)
        doc = self._get_or_raise(candidate_id)
        doc.set("experience", experience)
        doc.save(ignore_permissions=True)
        return self.get_candidate(candidate_id)

    def get_skills(self, candidate_id: str) -> list[dict]:
        """Return all Candidate Skill records for a Candidate."""
        doc = self._get_or_raise(candidate_id)
        return self._serialize_child_table(doc.get("skills") or [])

    def update_skills(self, candidate_id: str, skills: list) -> dict:
        """Replace all Candidate Skill records for a Candidate."""
        self._validator.validate_skills(skills)
        doc = self._get_or_raise(candidate_id)
        doc.set("skills", skills)
        doc.save(ignore_permissions=True)
        return self.get_candidate(candidate_id)

    def get_certifications(self, candidate_id: str) -> list[dict]:
        """Return all Candidate Certification records for a Candidate."""
        doc = self._get_or_raise(candidate_id)
        return self._serialize_child_table(doc.get("certifications") or [])

    def update_certifications(self, candidate_id: str, certifications: list) -> dict:
        """Replace all Candidate Certification records for a Candidate."""
        self._validator.validate_certifications(certifications)
        doc = self._get_or_raise(candidate_id)
        doc.set("certifications", certifications)
        doc.save(ignore_permissions=True)
        return self.get_candidate(candidate_id)

    def get_languages(self, candidate_id: str) -> list[dict]:
        """Return all Candidate Language records for a Candidate."""
        doc = self._get_or_raise(candidate_id)
        return self._serialize_child_table(doc.get("languages") or [])

    def update_languages(self, candidate_id: str, languages: list) -> dict:
        """Replace all Candidate Language records for a Candidate."""
        self._validator.validate_languages(languages)
        doc = self._get_or_raise(candidate_id)
        doc.set("languages", languages)
        doc.save(ignore_permissions=True)
        return self.get_candidate(candidate_id)

    def get_documents(self, candidate_id: str) -> list[dict]:
        """Return all Candidate Document records for a Candidate."""
        doc = self._get_or_raise(candidate_id)
        return self._serialize_child_table(doc.get("documents") or [])

    def update_documents(self, candidate_id: str, documents: list) -> dict:
        """Replace all Candidate Document records for a Candidate."""
        self._validator.validate_documents(documents)
        doc = self._get_or_raise(candidate_id)
        doc.set("documents", documents)
        doc.save(ignore_permissions=True)
        return self.get_candidate(candidate_id)

    def update_passport_and_visa(self, candidate_id: str, data: dict) -> dict:
        """Update passport and visa details for a Candidate."""
        self._validator.validate_passport_and_visa(data)
        doc = self._get_or_raise(candidate_id)
        for field in ("passport_number", "passport_expiry", "visa_status", "work_permit"):
            if field in data:
                setattr(doc, field, data[field])
        doc.save(ignore_permissions=True)
        return self.get_candidate(candidate_id)

    def list_international_candidates(
        self,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
        filters: dict | None = None,
        order_by: str = "creation",
        order_dir: str = "desc",
    ) -> dict:
        """Return a paginated list of International Candidates based on passport, visa, work permit, or country mismatch."""
        page, page_size = self._sanitise_pagination(page, page_size)
        order_clause = self._sanitise_order_by(order_by, order_dir)
        user_filters = filters or {}

        conditions = [
            "(work_permit = 1 OR (visa_status IS NOT NULL AND visa_status != '') OR (passport_number IS NOT NULL AND passport_number != '') OR (nationality IS NOT NULL AND country IS NOT NULL AND nationality != country))"
        ]
        values = []

        if user_filters.get("status"):
            conditions.append("status = %s")
            values.append(user_filters["status"])
        if user_filters.get("nationality"):
            conditions.append("nationality = %s")
            values.append(user_filters["nationality"])
        if user_filters.get("country"):
            conditions.append("country = %s")
            values.append(user_filters["country"])
        if user_filters.get("visa_status"):
            conditions.append("visa_status = %s")
            values.append(user_filters["visa_status"])
        if user_filters.get("work_permit") is not None:
            conditions.append("work_permit = %s")
            values.append(1 if str(user_filters["work_permit"]).lower() in ("true", "1") else 0)

        where_clause = " AND ".join(conditions)

        count_query = f"SELECT COUNT(*) FROM `tabCandidate` WHERE {where_clause}"
        total = frappe.db.sql(count_query, tuple(values))[0][0]

        offset = (page - 1) * page_size
        query = f"SELECT name FROM `tabCandidate` WHERE {where_clause} ORDER BY {order_clause} LIMIT %s OFFSET %s"
        query_vals = tuple(values) + (page_size, offset)
        rows = frappe.db.sql(query, query_vals, as_dict=True)

        candidate_ids = [r["name"] for r in rows]
        batch_applications = self._get_batch_latest_applications(candidate_ids)

        data_list = []
        for cid in candidate_ids:
            cand_doc = self._get_or_raise(cid)
            data_list.append(
                self._serialize_candidate(
                    cand_doc, fields=_DETAIL_FIELDS, application=batch_applications.get(cid)
                )
            )

        return {
            "data": data_list,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def list_domestic_candidates(
        self,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
        filters: dict | None = None,
        order_by: str = "creation",
        order_dir: str = "desc",
    ) -> dict:
        """List domestic candidates with database-level pagination and filtering.

        Domestic candidates are defined as candidate records where:
        - work_permit is 0 or NULL
        - visa_status is NULL, empty, or 'Not Applicable'
        - passport_number is NULL or empty
        - nationality and country match or either is unspecified
        """
        user_filters = filters or {}

        valid_order_fields = {
            "creation",
            "modified",
            "first_name",
            "last_name",
            "status",
            "years_of_experience",
        }
        safe_order_by = order_by if order_by in valid_order_fields else "creation"
        safe_order_dir = "ASC" if order_dir.lower() == "asc" else "DESC"
        order_clause = f"`{safe_order_by}` {safe_order_dir}"

        conditions = [
            "(work_permit = 0 OR work_permit IS NULL)",
            "(visa_status IS NULL OR visa_status = '' OR visa_status = 'Not Applicable')",
            "(passport_number IS NULL OR passport_number = '')",
            "(nationality IS NULL OR country IS NULL OR nationality = country)",
        ]
        values = []

        if user_filters.get("search"):
            conditions.append(
                "(first_name LIKE %s OR last_name LIKE %s OR email LIKE %s OR candidate_name LIKE %s)"
            )
            term = f"%{user_filters['search']}%"
            values.extend([term, term, term, term])

        if user_filters.get("status"):
            conditions.append("status = %s")
            values.append(user_filters["status"])
        if user_filters.get("profession"):
            conditions.append("profession = %s")
            values.append(user_filters["profession"])
        if user_filters.get("city"):
            conditions.append("city = %s")
            values.append(user_filters["city"])
        if user_filters.get("country"):
            conditions.append("country = %s")
            values.append(user_filters["country"])

        where_clause = " AND ".join(conditions)

        count_query = f"SELECT COUNT(*) FROM `tabCandidate` WHERE {where_clause}"
        total = frappe.db.sql(count_query, tuple(values))[0][0]

        offset = (page - 1) * page_size
        query = f"SELECT name FROM `tabCandidate` WHERE {where_clause} ORDER BY {order_clause} LIMIT %s OFFSET %s"
        query_vals = tuple(values) + (page_size, offset)
        rows = frappe.db.sql(query, query_vals, as_dict=True)

        candidate_ids = [r["name"] for r in rows]
        batch_applications = self._get_batch_latest_applications(candidate_ids)

        data_list = []
        for cid in candidate_ids:
            cand_doc = self._get_or_raise(cid)
            data_list.append(
                self._serialize_candidate(
                    cand_doc, fields=_DETAIL_FIELDS, application=batch_applications.get(cid)
                )
            )

        return {
            "data": data_list,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get_domestic_candidate(self, candidate_id: str) -> dict:
        """Retrieve details for a domestic candidate."""
        return self.get_candidate(candidate_id=candidate_id)

    def update_domestic_candidate(self, candidate_id: str, data: dict) -> dict:
        """Update profile details for a domestic candidate."""
        return self.update_candidate(candidate_id=candidate_id, data=data)

    def get_profile_completeness(self, candidate_id: str) -> dict:
        """Calculate a granular profile completeness score for the Candidate."""
        doc = self._get_or_raise(candidate_id)

        scores = {}
        missing = []

        # 1. Personal & Basic Info (20%)
        personal_fields = ["first_name", "last_name", "date_of_birth", "gender"]
        p_filled = sum(1 for f in personal_fields if doc.get(f))
        scores["personal_info"] = round((p_filled / len(personal_fields)) * 20, 2)
        if p_filled < len(personal_fields):
            missing.extend([f for f in personal_fields if not doc.get(f)])

        # 2. Contact & Location (15%)
        contact_fields = ["email", "mobile_no", "city", "country"]
        c_filled = sum(1 for f in contact_fields if doc.get(f))
        scores["contact_location"] = round((c_filled / len(contact_fields)) * 15, 2)
        if c_filled < len(contact_fields):
            missing.extend([f for f in contact_fields if not doc.get(f)])

        # 3. Professional Info (15%)
        prof_fields = ["current_job_title", "years_of_experience", "notice_period", "expected_salary"]
        pr_filled = sum(1 for f in prof_fields if doc.get(f) is not None and doc.get(f) != "")
        scores["professional_info"] = round((pr_filled / len(prof_fields)) * 15, 2)
        if pr_filled < len(prof_fields):
            missing.extend([f for f in prof_fields if doc.get(f) is None or doc.get(f) == ""])

        # 4. Education (15%)
        edu = doc.get("education") or []
        scores["education"] = 15 if len(edu) > 0 else 0
        if len(edu) == 0:
            missing.append("education")

        # 5. Experience (15%)
        exp = doc.get("experience") or []
        scores["experience"] = 15 if len(exp) > 0 else 0
        if len(exp) == 0:
            missing.append("experience")

        # 6. Skills (10%)
        skills = doc.get("skills") or []
        scores["skills"] = 10 if len(skills) >= 1 else 0
        if len(skills) == 0:
            missing.append("skills")

        # 7. Resume & Documents / Passport (10%)
        docs = doc.get("documents") or []
        has_resume = bool(doc.get("resume")) or any(d.get("document_type") == "Resume" for d in docs)
        scores["documents"] = 10 if has_resume else 0
        if not has_resume:
            missing.append("resume")

        total_score = int(sum(scores.values()))

        # Save score back to document profile_completion field
        if doc.profile_completion != total_score:
            doc.profile_completion = total_score
            doc.save(ignore_permissions=True)

        return {
            "candidate_id": candidate_id,
            "overall_completeness": total_score,
            "section_scores": scores,
            "missing_fields": missing,
        }

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
    def _get_batch_latest_applications(candidate_ids: list[str]) -> dict[str, dict]:
        """Fetch the latest Job Application record for a list of Candidate IDs in batch.

        Avoids N+1 queries by grouping and fetching all applications for candidate IDs
        joined with Job Opening details in 1 aggregated DB query.
        """
        valid_ids = [cid for cid in candidate_ids if cid]
        if not valid_ids:
            return {}

        app_rows = frappe.db.sql(
            """
            SELECT
                app.name AS application_name,
                app.candidate AS candidate_id,
                app.job_opening AS job_id,
                app.applied_on AS applied_on,
                app.creation AS creation,
                app.current_stage AS current_stage,
                app.assigned_recruiter AS app_recruiter,
                job.job_title AS job_title,
                job.department AS department,
                job.recruiter AS job_recruiter
            FROM `tabJob Application` app
            LEFT JOIN `tabJob Opening` job ON app.job_opening = job.name
            WHERE app.candidate IN %s
            ORDER BY app.applied_on DESC, app.creation DESC
            """,
            (tuple(valid_ids),),
            as_dict=True,
        )

        latest_apps: dict[str, dict] = {}
        for row in app_rows:
            cid = row.get("candidate_id")
            if cid and cid not in latest_apps:
                recruiter = row.get("app_recruiter") or row.get("job_recruiter") or None
                raw_applied = row.get("applied_on") or (str(row.get("creation"))[:10] if row.get("creation") else None)
                if hasattr(raw_applied, "strftime"):
                    applied_at = raw_applied.strftime("%Y-%m-%d")
                elif raw_applied:
                    applied_at = str(raw_applied)[:10]
                else:
                    applied_at = None

                latest_apps[cid] = {
                    "application_name": row.get("application_name"),
                    "job_id": row.get("job_id"),
                    "job_title": row.get("job_title"),
                    "department": row.get("department"),
                    "applied_at": applied_at,
                    "recruiter": recruiter,
                    "current_stage": row.get("current_stage"),
                }

        return latest_apps

    @staticmethod
    def _serialize_child_table(child_records: list) -> list[dict]:
        """Convert child document list to clean list of dicts excluding Frappe metadata."""
        serialized = []
        for row in child_records:
            if isinstance(row, dict):
                r_dict = {k: v for k, v in row.items() if k not in _FRAPPE_METADATA_FIELDS}
            else:
                r_dict = {k: getattr(row, k) for k in row.as_dict().keys() if k not in _FRAPPE_METADATA_FIELDS}
            serialized.append(r_dict)
        return serialized

    @staticmethod
    def _serialize_candidate(doc, fields: list[str], application: dict | None = None) -> dict:
        """Serialise a Frappe Candidate Document to a plain, JSON-safe dict.

        Strips metadata fields and populates contract aliases expected by frontends:
        - phone / mobile_number -> mobile_no
        - full_name -> first_name + middle_name + last_name
        - linkedin_url -> linkedin
        - portfolio_url -> portfolio
        - location / current_location -> city, state, country or preferred_location
        - experience / total_experience_years -> years_of_experience
        - salary -> expected_salary
        - bio -> None (if missing)
        - application -> { job_id, job_title, department, applied_at, recruiter, current_stage }
        - latest_application, latest_job, latest_job_title, latest_application_date, latest_application_stage, latest_recruiter
        """
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

        # Dynamic Full Name Alias
        fn = data.get("first_name", "") or ""
        mn = data.get("middle_name", "") or ""
        ln = data.get("last_name", "") or ""
        name_parts = [p for p in (fn, mn, ln) if p]
        if name_parts:
            data["full_name"] = " ".join(name_parts)

        # Phone Aliases
        if "mobile_no" in data:
            data["phone"] = data["mobile_no"]
            data["mobile_number"] = data["mobile_no"]

        # Social Link Aliases
        if "linkedin" in data:
            data["linkedin_url"] = data["linkedin"]
        if "portfolio" in data:
            data["portfolio_url"] = data["portfolio"]

        # Experience & Salary Aliases
        if "years_of_experience" in data:
            data["experience"] = data["years_of_experience"]
            data["total_experience_years"] = data["years_of_experience"]
        if "expected_salary" in data:
            data["salary"] = data["expected_salary"]

        # Location Aliases
        loc_parts = [str(data[k]) for k in ("city", "state", "country") if data.get(k)]
        if loc_parts:
            loc_str = ", ".join(loc_parts)
            data["location"] = loc_str
            data["current_location"] = loc_str
        elif data.get("preferred_location"):
            data["location"] = data["preferred_location"]
            data["current_location"] = data["preferred_location"]
        else:
            data["location"] = None
            data["current_location"] = None

        if "bio" not in data:
            data["bio"] = None

        # Passport & Visa & International indicator
        pass_num = data.get("passport_number") or (doc.get("passport_number") if not isinstance(doc, dict) else None)
        pass_exp = data.get("passport_expiry") or (doc.get("passport_expiry") if not isinstance(doc, dict) else None)
        visa_st = data.get("visa_status") or (doc.get("visa_status") if not isinstance(doc, dict) else None)
        work_perm = data.get("work_permit") if "work_permit" in data else (doc.get("work_permit") if not isinstance(doc, dict) else 0)

        data["passport_number"] = pass_num
        data["passport_expiry"] = str(pass_exp) if pass_exp else None
        data["visa_status"] = visa_st
        data["work_permit"] = bool(work_perm)

        nat = data.get("nationality") or (doc.get("nationality") if not isinstance(doc, dict) else None)
        ctry = data.get("country") or (doc.get("country") if not isinstance(doc, dict) else None)
        is_intl = bool(
            (nat and ctry and str(nat).strip().lower() != str(ctry).strip().lower())
            or data["work_permit"]
            or (data["visa_status"] and str(data["visa_status"]).strip().lower() not in ("", "not applicable"))
            or data["passport_number"]
        )
        data["is_international"] = is_intl
        data["is_domestic"] = not is_intl

        # Include child tables if available on doc
        if not isinstance(doc, dict):
            data["education"] = CandidateService._serialize_child_table(doc.get("education") or [])
            data["experience_list"] = CandidateService._serialize_child_table(doc.get("experience") or [])
            data["skills"] = CandidateService._serialize_child_table(doc.get("skills") or [])
            data["languages"] = CandidateService._serialize_child_table(doc.get("languages") or [])
            data["certifications"] = CandidateService._serialize_child_table(doc.get("certifications") or [])
            data["documents"] = CandidateService._serialize_child_table(doc.get("documents") or [])

        # Enrichment: latest Job Application details
        if application:
            data["application"] = {
                "job_id": application.get("job_id"),
                "job_title": application.get("job_title"),
                "department": application.get("department"),
                "applied_at": application.get("applied_at"),
                "recruiter": application.get("recruiter"),
                "current_stage": application.get("current_stage"),
                # Aliases for frontend UI compatibility
                "jobId": application.get("job_id"),
                "jobTitle": application.get("job_title"),
                "appliedAt": application.get("applied_at"),
                "currentStage": application.get("current_stage"),
            }
            data["latest_application"] = application.get("application_name")
            data["latest_job"] = application.get("job_id")
            data["latest_job_title"] = application.get("job_title")
            data["latest_application_date"] = application.get("applied_at")
            data["latest_application_stage"] = application.get("current_stage")
            data["latest_recruiter"] = application.get("recruiter")
        else:
            data["application"] = None
            data["latest_application"] = None
            data["latest_job"] = None
            data["latest_job_title"] = None
            data["latest_application_date"] = None
            data["latest_application_stage"] = None
            data["latest_recruiter"] = None

        return data

    @staticmethod
    def _apply_changed_fields(doc, data: dict) -> dict:
        """Apply only genuinely changed fields onto a Frappe Document object."""
        changed: dict = {}
        meta = frappe.get_meta(doc.doctype)

        aliases = {
            "phone": "mobile_no",
            "mobile_number": "mobile_no",
            "linkedin_url": "linkedin",
            "portfolio_url": "portfolio",
            "experience": "years_of_experience",
            "total_experience_years": "years_of_experience",
            "salary": "expected_salary",
            "location": "preferred_location",
            "current_location": "preferred_location",
        }

        normalized_data = {}
        for k, v in data.items():
            target_key = aliases.get(k, k)
            normalized_data[target_key] = v

        child_table_fields = {"education", "experience", "skills", "languages", "certifications", "documents"}

        for field, new_value in normalized_data.items():
            if field in child_table_fields:
                if isinstance(new_value, list):
                    doc.set(field, new_value)
                    changed[field] = new_value
                continue

            if not meta.has_field(field):
                continue

            current_value = doc.get(field)
            if current_value != new_value:
                setattr(doc, field, new_value)
                changed[field] = new_value
        return changed

    @staticmethod
    def _build_orm_filters(filters: dict) -> dict:
        """Construct a Frappe ORM filter dict from the caller-supplied filter map."""
        orm: dict = {}

        if filters.get("status"):
            orm["status"] = filters["status"]
        if filters.get("profession"):
            orm["profession"] = filters["profession"]
        if filters.get("city"):
            orm["city"] = filters["city"]
        if filters.get("country"):
            orm["country"] = filters["country"]
        if filters.get("nationality"):
            orm["nationality"] = filters["nationality"]
        if filters.get("visa_status"):
            orm["visa_status"] = filters["visa_status"]
        if filters.get("work_permit") is not None:
            orm["work_permit"] = 1 if str(filters["work_permit"]).lower() in ("true", "1") else 0
        if filters.get("location") or filters.get("current_location"):
            loc = filters.get("location") or filters.get("current_location")
            orm["preferred_location"] = ["like", f"%{loc}%"]

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
                    "entity_type": "Candidate",
                    "entity_id": entity_id,
                    "action_url": action_url,
                    "action_label": action_label,
                },
                company=target_company,
                recipient=recipient,
                created_by=getattr(frappe.session, "user", "System"),
            )
        except Exception as exc:
            frappe.logger().error(f"Candidate notification error: {exc}")

