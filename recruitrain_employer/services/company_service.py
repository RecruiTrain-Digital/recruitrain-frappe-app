# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.services.company_service
===============================================

Company Business Logic Service.

Architecture
------------
All database operations for the Company domain are centralised here.
The API layer (``recruitrain_employer.api.company``) must not access
``frappe.get_doc``, ``frappe.get_all``, or ``frappe.db`` directly.

Request/Response Flow::

    React
      │
      ▼
    api/company.py            ← Parse input, invoke service, format response
      │
      ▼
    CompanyService            ← Business logic, ORM queries
      │
      ▼
    CompanyValidator          ← Normalization + validation
      │
      ▼
    Frappe ORM / MariaDB

Normalization Contract
-----------------------
``CompanyValidator.validate_create`` and ``validate_update`` normalize
``email``, ``phone``, and ``website`` **in-place** on the input ``data`` dict.
``CompanyService`` therefore always receives — and stores — canonical values:

- ``email``   → trimmed, lowercase.
- ``phone``   → cosmetic punctuation stripped.
- ``website`` → scheme prepended if missing, trailing slash stripped.

Serializer Safety
-----------------
``_serialize_company`` actively excludes Frappe internal metadata fields
(``owner``, ``modified_by``, ``creation``, ``modified``, ``idx``,
``docstatus``, ``doctype``, ``parent``, ``parentfield``, ``parenttype``)
from every response.  Only fields explicitly listed in ``_LIST_FIELDS`` or
``_DETAIL_FIELDS`` are returned, and those are additionally filtered through
``_FRAPPE_METADATA_FIELDS`` as a second gate.

Changed-Field Tracking
-----------------------
``_apply_changed_fields`` writes only fields whose values differ from the
current document, preventing unnecessary Frappe dirty-field tracking and
producing a clean diff dict for future Activity Log integration.

Scope — Sprint: Company Management Foundation
----------------------------------------------
This sprint implements CRUD operations on the **Company** DocType only.

Out of scope (implemented in future sprints):
- Employer Users (Company ↔ User linking)
- Departments
- Job Openings
- Company Statistics and Analytics
- Logo Upload
- Company Settings
- Notifications and Activity Logs
- Soft-delete / archive workflow

DocTypes Used
-------------
- Company

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
    DOCTYPE_COMPANY,
    MAX_PAGE_SIZE,
)
from recruitrain_employer.utils.exceptions import (
    ATSConflictError,
    ATSNotFoundError,
    ATSValidationError,
)
from recruitrain_employer.validators.company_validator import CompanyValidator


# ---------------------------------------------------------------------------
# Module-Level Constants
# ---------------------------------------------------------------------------

#: Fields used to search across Company records.
#: To add a new searchable field, append it here — no other changes needed.
SEARCHABLE_FIELDS: tuple[str, ...] = (
    "company_name",
    "email",
    "phone",
    "website",
    "industry",
    "city",
    "country",
)

#: Fields callers may pass to ``order_by``.
#: Any value not in this set is silently replaced with ``"creation"``
#: to prevent malformed queries.
ALLOWED_SORT_FIELDS: frozenset[str] = frozenset(
    [
        "creation",
        "modified",
        "company_name",
        "industry",
        "country",
        "status",
    ]
)

#: Frappe internal metadata fields that must never appear in API responses.
#: Applied as a second exclusion gate in ``_serialize_company`` regardless of
#: what field list is passed — defence-in-depth against accidental exposure.
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
    "company_name",
    "industry",
    "email",
    "phone",
    "website",
    "city",
    "country",
    "status",
]

#: Fields returned in a full Company detail response.
#: All fieldnames must exist in company.json.
#: Must not overlap with ``_FRAPPE_METADATA_FIELDS``.
_DETAIL_FIELDS: list[str] = _LIST_FIELDS + [
    "description",
    "state",
    "address_line_1",
    "address_line_2",
    "postal_code",
    "founded_year",
    "company_size",
    "linkedin",
    "twitter",
    "facebook",
    "instagram",
    "logo",
    "banner",
    "primary_color",
    "secondary_color",
    "legal_name",
    "company_code",
    "alternate_phone",
    "hr_email",
    "support_email",
    "verified",
    "active",
]


class CompanyService:
    """Encapsulates business logic for Company profile operations.

    All database reads and writes for the Company domain go through this class.
    No DocType access is permitted in the API layer.

    Usage
    -----
    ::

        service = CompanyService()
        company = service.get_company("COMP-0001")
    """

    def __init__(self) -> None:
        self._validator = CompanyValidator()

    # ------------------------------------------------------------------
    # CRUD Methods
    # ------------------------------------------------------------------

    def create_company(self, data: dict) -> dict:
        """Create a new Company record.

        Normalization is performed by ``CompanyValidator.validate_create``
        in-place on ``data`` before the record is saved.

        Parameters
        ----------
        data : dict
            Company field values.  Must include at a minimum:
            ``company_name``, ``industry``.
            ``email`` will be normalized (trimmed, lowercased) in-place if provided.
            ``phone`` will be normalized (punctuation stripped) in-place if provided.
            ``website`` will have scheme prepended and trailing slash stripped in-place
            if provided.

        Returns
        -------
        dict
            The newly created Company document serialised by ``_serialize_company()``.

        Raises
        ------
        ATSValidationError
            If required fields are missing or any value is invalid.
        ATSConflictError
            If a Company with the same ``company_name`` already exists.

        TODO: Log company creation to Activity Log via ActivityLogService.
        TODO: Notify administrators via NotificationService.
        """
        # validate_create normalizes email, phone, website in-place before checking.
        self._validator.validate_create(data)

        # Uniqueness check uses the normalized company_name from data.
        self._assert_name_unique(data["company_name"])

        doc = frappe.new_doc(DOCTYPE_COMPANY)
        self._apply_changed_fields(doc, data)
        try:
            doc.insert(ignore_permissions=True)
        except DuplicateEntryError as exc:
            raise ATSConflictError(
                f"A Company named '{data.get('company_name')}' already exists.",
                details={"field": "company_name", "value": data.get("company_name")},
            ) from exc

        return self._serialize_company(doc, fields=_DETAIL_FIELDS)

    def get_company(self, company_id: str) -> dict:
        """Retrieve a full Company profile by record name.

        Parameters
        ----------
        company_id : str
            The ``name`` (primary key) of the Company record.

        Returns
        -------
        dict
            The Company document serialised by ``_serialize_company()``.
            Only business-facing fields are included; Frappe metadata is
            excluded by the serialiser.

        Raises
        ------
        ATSValidationError
            If ``company_id`` is empty.
        ATSNotFoundError
            If no Company with the given ID exists.

        TODO: Attach summary stats (open job count, etc.) once those
              sprints are implemented.
        """
        if not company_id:
            raise ATSValidationError("company_id is required.", field="company_id")

        doc = self._get_or_raise(company_id)
        return self._serialize_company(doc, fields=_DETAIL_FIELDS)

    def update_company(self, company_id: str, data: dict) -> dict:
        """Apply a partial update to an existing Company record.

        Only fields whose values have **changed** from the current document
        are written.  Identical values are skipped, preventing unnecessary
        dirty-field tracking and keeping the Activity Log diff clean.

        Parameters
        ----------
        company_id : str
            The ``name`` of the Company to update.
        data : dict
            Partial Company fields to apply.  Only fields in
            ``COMPANY_UPDATABLE_FIELDS`` are accepted.
            ``phone`` and ``website`` are normalized in-place if provided.

        Returns
        -------
        dict
            The updated Company document serialised by ``_serialize_company()``.

        Raises
        ------
        ATSValidationError
            If ``company_id`` is empty, ``data`` is empty, or any field
            is not updatable.
        ATSNotFoundError
            If no Company with the given ID exists.

        TODO: Pass ``changed_fields`` to ActivityLogService once implemented.
        """
        if not company_id:
            raise ATSValidationError("company_id is required.", field="company_id")

        # validate_update normalizes phone and website in-place before checking.
        self._validator.validate_update(data)

        doc = self._get_or_raise(company_id)

        # Apply only changed fields; the returned dict is ready for the
        # Activity Log in a future sprint.
        changed_fields = self._apply_changed_fields(doc, data)

        if changed_fields:
            try:
                doc.save(ignore_permissions=True)
            except DuplicateEntryError as exc:
                raise ATSConflictError(
                    f"Company conflict during update.",
                    details={"company_id": company_id},
                ) from exc
            # TODO: Log changed_fields to Activity Log via ActivityLogService.

        return self._serialize_company(doc, fields=_DETAIL_FIELDS)

    # TODO: Replace hard delete with an archive/deactivate workflow
    #       during the Company Lifecycle sprint.  Most ATS systems never
    #       permanently delete companies because they are linked to historical
    #       job openings, applications, and interviews.
    def delete_company(self, company_id: str) -> None:
        """Permanently delete a Company record.

        Performs a safe delete — if Frappe detects linked records that prevent
        deletion, an ``ATSConflictError`` is raised with a user-friendly message
        instead of exposing the raw Frappe exception.

        Parameters
        ----------
        company_id : str
            The ``name`` of the Company to delete.

        Raises
        ------
        ATSValidationError
            If ``company_id`` is empty.
        ATSNotFoundError
            If no Company with the given ID exists.
        ATSConflictError
            If the Company has linked records (e.g. Job Openings, Employer Users)
            that prevent deletion.

        TODO: Log deletion to Activity Log via ActivityLogService.
        """
        if not company_id:
            raise ATSValidationError("company_id is required.", field="company_id")

        # Confirm existence before attempting delete.
        self._get_or_raise(company_id)

        try:
            frappe.delete_doc(
                DOCTYPE_COMPANY,
                company_id,
                ignore_permissions=True,
                force=False,  # Respect Frappe's link-existence checks.
            )
        except LinkExistsError as exc:
            raise ATSConflictError(
                f"Company '{company_id}' cannot be deleted because it is "
                "referenced by one or more linked records (e.g. Job Openings, "
                "Employer Users). Please resolve those references first.",
                details={"company_id": company_id},
            ) from exc

    def list_companies(
        self,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
        filters: dict | None = None,
        order_by: str = "creation",
        order_dir: str = "desc",
    ) -> dict:
        """Return a paginated, filtered list of Company records.

        Parameters
        ----------
        page : int, optional
            Page number (1-indexed).  Defaults to ``DEFAULT_PAGE``.
        page_size : int, optional
            Records per page.  Capped at ``MAX_PAGE_SIZE``.
        filters : dict or None, optional
            Optional field filters.  Supported keys today:

            - ``industry`` (str) — filter by Industry.
            - ``status``   (str) — filter by Company status field.
            - ``country``  (str) — filter by country.
            - ``state``    (str) — filter by state/region.
            - ``city``     (str) — filter by city.

            Additional keys can be added to ``_build_orm_filters`` without
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
        TODO: Add company_size filter in a future sprint.
        """
        page, page_size = self._sanitise_pagination(page, page_size)
        order_clause = self._sanitise_order_by(order_by, order_dir)
        orm_filters = self._build_orm_filters(filters or {})

        total = frappe.db.count(DOCTYPE_COMPANY, filters=orm_filters)

        records = frappe.get_list(
            DOCTYPE_COMPANY,
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

    def search_companies(
        self,
        search: str,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
        filters: dict | None = None,
        order_by: str = "creation",
        order_dir: str = "desc",
    ) -> dict:
        """Search Companies across ``SEARCHABLE_FIELDS`` using a single query string.

        Generates an ``OR`` filter across all fields defined in
        ``SEARCHABLE_FIELDS``.  To add a new field to the search scope,
        append it to ``SEARCHABLE_FIELDS`` — no other code changes needed.

        The search term is lowercased and trimmed before building the ``LIKE``
        filters.  MariaDB's default collation (``utf8mb4_general_ci``) is
        already case-insensitive; lowercasing is an additional safety measure
        for ``_bin`` collation environments.

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
            (same keys as ``list_companies``).
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

        total = frappe.db.count(DOCTYPE_COMPANY, filters=orm_filters, or_filters=or_filters)

        records = frappe.get_list(
            DOCTYPE_COMPANY,
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
    # Profile Endpoints (used by Frontend companyApi.js)
    # ------------------------------------------------------------------

    def get_company_profile(self, company_id: str) -> dict:
        """Return the full Company profile serialised with the frontend field contract.

        Returns every field required by the frontend including logo, banner,
        branding, contact, address, and social media fields.  All field names
        are canonical schema names (snake_case); the frontend normalizer in
        ``companyApi.js`` maps them to camelCase.

        Parameters
        ----------
        company_id : str
            The ``name`` of the Company record.

        Returns
        -------
        dict
            Full Company document serialised via ``_serialize_company`` with
            ``_DETAIL_FIELDS``.

        Raises
        ------
        ATSValidationError
            If ``company_id`` is empty.
        ATSNotFoundError
            If the Company does not exist.
        """
        if not company_id:
            raise ATSValidationError("company_id is required.", field="company_id")
        doc = self._get_or_raise(company_id)
        return self._serialize_company_profile(doc)

    def update_company_profile(self, company_id: str, data: dict) -> dict:
        """Apply a partial update to a Company record via the profile endpoint.

        Delegates field validation and changed-field tracking to ``update_company``,
        then re-serialises the result using ``_serialize_company_profile`` so the
        frontend receives canonical fields **and** legacy alias keys in one response.

        Parameters
        ----------
        company_id : str
            The ``name`` of the Company to update.
        data : dict
            Partial Company fields.  Only fields in
            ``COMPANY_UPDATABLE_FIELDS`` are accepted.

        Returns
        -------
        dict
            The updated Company document with both canonical and alias fields.
        """
        if not company_id:
            raise ATSValidationError("company_id is required.", field="company_id")

        self._validator.validate_update(data)
        doc = self._get_or_raise(company_id)
        changed_fields = self._apply_changed_fields(doc, data)

        if changed_fields:
            from frappe.exceptions import DuplicateEntryError
            try:
                doc.save(ignore_permissions=True)
            except DuplicateEntryError as exc:
                raise ATSConflictError(
                    "Company conflict during profile update.",
                    details={"company_id": company_id},
                ) from exc

        return self._serialize_company_profile(doc)

    def upload_company_logo(self, company_id: str, file_content: bytes, file_name: str, content_type: str) -> dict:
        """Upload or replace the Company logo and persist the URL on the document.

        Workflow
        --------
        1. Validate MIME type against ``ALLOWED_IMAGE_TYPES``.
        2. Validate file size against ``MAX_LOGO_SIZE_MB``.
        3. Create a Frappe ``File`` record attached to this Company.
        4. Set ``company.logo`` to the new file URL and save.
        5. Return ``{"logo_url": "<url>"}`` for the frontend.

        Parameters
        ----------
        company_id : str
            The ``name`` of the Company to attach the logo to.
        file_content : bytes
            Raw file bytes from the upload.
        file_name : str
            Original file name (used for extension detection).
        content_type : str
            MIME type of the upload (e.g. ``"image/png"``).

        Returns
        -------
        dict
            ``{"logo_url": "<frappe file url>"}``

        Raises
        ------
        ATSValidationError
            If the file type is not allowed or exceeds the size limit.
        ATSNotFoundError
            If the Company record does not exist.
        """
        from recruitrain_employer.utils.constants import ALLOWED_IMAGE_TYPES, MAX_LOGO_SIZE_MB

        # 1. Validate MIME type.
        if content_type not in ALLOWED_IMAGE_TYPES:
            raise ATSValidationError(
                f"File type '{content_type}' is not allowed for company logos. "
                f"Allowed types: {', '.join(ALLOWED_IMAGE_TYPES)}.",
                field="logo",
            )

        # 2. Validate file size.
        max_bytes = MAX_LOGO_SIZE_MB * 1024 * 1024
        if len(file_content) > max_bytes:
            raise ATSValidationError(
                f"Logo file exceeds the maximum allowed size of {MAX_LOGO_SIZE_MB} MB.",
                field="logo",
            )

        # 3. Confirm company exists.
        doc = self._get_or_raise(company_id)

        # 4. Create Frappe File record attached to this Company.
        file_doc = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": file_name,
                "content": file_content,
                "attached_to_doctype": DOCTYPE_COMPANY,
                "attached_to_name": company_id,
                "attached_to_field": "logo",
                "is_private": 0,
            }
        )
        file_doc.insert(ignore_permissions=True)

        logo_url: str = file_doc.file_url

        # 5. Update Company.logo with the new file URL.
        doc.db_set("logo", logo_url)

        return {"logo_url": logo_url}

    # ------------------------------------------------------------------
    # Sub-Resource Methods (Future Sprints)
    # ------------------------------------------------------------------

    def get_company_jobs(self, company_id: str) -> list:
        """Return all active Job Openings belonging to the Company.

        TODO: Implement in the Job Opening sprint.
        TODO: frappe.get_all(DOCTYPE_JOB_OPENING, filters={"company": company_id})
        """
        pass

    def get_company_stats(self, company_id: str) -> dict:
        """Return high-level statistics for the Company.

        Planned Stats
        -------------
        - open_jobs          : int
        - total_applications : int
        - interviews_this_week: int
        - pending_offers     : int

        TODO: Implement in the Dashboard/Analytics sprint.
        TODO: Use frappe.db.count() scoped to company_id for each stat.
        """
        pass

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _get_or_raise(self, company_id: str):
        """Fetch a Company document or raise ``ATSNotFoundError``.

        Parameters
        ----------
        company_id : str
            The Company record name.

        Returns
        -------
        frappe.Document
            The live Frappe Document object.

        Raises
        ------
        ATSNotFoundError
            If the record does not exist.
        """
        if not frappe.db.exists(DOCTYPE_COMPANY, company_id):
            raise ATSNotFoundError(
                f"Company '{company_id}' was not found.",
                doctype=DOCTYPE_COMPANY,
                name=company_id,
            )
        return frappe.get_doc(DOCTYPE_COMPANY, company_id)

    def _assert_name_unique(self, company_name: str) -> None:
        """Raise ``ATSConflictError`` if a Company with this name already exists.

        ``company_name`` is the business identity of a Company record.
        Duplicate names are rejected at creation time.

        Parameters
        ----------
        company_name : str
            The company name to check for uniqueness.

        Raises
        ------
        ATSConflictError
            If the name is already registered to an existing Company.
        """
        if frappe.db.exists(DOCTYPE_COMPANY, {"company_name": company_name}):
            raise ATSConflictError(
                f"A Company named '{company_name}' already exists.",
                details={"field": "company_name", "value": company_name},
            )

    @staticmethod
    def _serialize_company(doc, fields: list[str]) -> dict:
        """Serialise a Frappe Company Document to a plain, JSON-safe dict.

        Named ``_serialize_company`` rather than a generic ``_doc_to_dict``
        because this helper is intentionally scoped to the Company domain.
        Each service module defines its own ``_serialize_*`` helper, making
        the origin immediately obvious and allowing domain-specific
        post-processing without coupling services together.

        Metadata Exclusion
        ------------------
        Applies a second exclusion gate: any field in ``_FRAPPE_METADATA_FIELDS``
        is stripped from the output regardless of whether it appears in
        ``fields``.  This provides defence-in-depth against accidental exposure
        of Frappe system data.

        Parameters
        ----------
        doc : frappe.Document
            The Company document to serialise.
        fields : list[str]
            The business-facing field names to include in the output dict.

        Returns
        -------
        dict
            A plain Python dict containing only non-metadata fields.
        """
        return {
            field: doc.get(field)
            for field in fields
            if field not in _FRAPPE_METADATA_FIELDS
        }

    @staticmethod
    def _serialize_company_profile(doc) -> dict:
        """Serialise a Company document with both canonical and frontend-alias keys.

        The frontend ``companyApi.js :: normalizeFromBackend`` reads a mix of
        canonical snake_case fields and legacy alias keys.  This serialiser
        emits **both** so the frontend contract is preserved without any
        frontend modification.

        Canonical fields returned
        -------------------------
        All fields in ``_DETAIL_FIELDS``: name, company_name, industry,
        email, phone, website, city, country, status, description, state,
        address_line_1, address_line_2, postal_code, founded_year, company_size,
        linkedin, twitter, facebook, instagram, logo, banner, primary_color,
        secondary_color, legal_name, company_code, alternate_phone, hr_email,
        support_email, verified, active.

        Frontend alias keys also emitted (read by normalizeFromBackend)
        ----------------------------------------------------------------
        - ``company_logo``   → alias for ``logo``
        - ``address_line1``  → alias for ``address_line_1``   (frontend uses ``street``)
        - ``pincode``        → alias for ``postal_code``       (frontend uses ``postalCode``)
        - ``industry_ids``   → ``[industry]`` single-element list (frontend reads as array)
        - ``about``          → alias for ``description``       (frontend uses ``about``)
        - ``contact_name``   → always ``null`` (not a schema field — placeholder for frontend)
        - ``contact_email``  → always ``null`` (not a schema field)
        - ``contact_phone``  → alias for ``phone``

        Parameters
        ----------
        doc : frappe.Document
            The Company document to serialise.

        Returns
        -------
        dict
            A plain Python dict suitable for JSON serialisation.
        """
        base: dict = {
            field: doc.get(field)
            for field in _DETAIL_FIELDS
            if field not in _FRAPPE_METADATA_FIELDS
        }

        # Inject frontend-expected alias keys without altering canonical fields.
        base["company_logo"]  = doc.get("logo")
        base["address_line1"] = doc.get("address_line_1")
        base["pincode"]       = doc.get("postal_code")
        base["industry_ids"]  = [doc.get("industry")] if doc.get("industry") else []
        base["about"]         = doc.get("description")
        base["contact_name"]  = None          # Not a schema field; placeholder for frontend
        base["contact_email"] = None          # Not a schema field; placeholder for frontend
        base["contact_phone"] = doc.get("phone")
        base["sub_industry"]  = None          # Not a schema field; placeholder for frontend

        return base

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
            A ``{field: new_value}`` dict containing only the fields that were
            actually changed.  An empty dict means no fields changed.

        Notes
        -----
        Unknown fields (not present as attributes on the document) are silently
        skipped to avoid attribute errors.

        The returned dict is intended for future Activity Log integration::

            changed = self._apply_changed_fields(doc, data)
            # TODO: ActivityLogService.log_update(company_id, changed)
        """
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

    @staticmethod
    def _build_orm_filters(filters: dict) -> dict:
        """Construct a Frappe ORM filter dict from the caller-supplied filter map.

        Supported Filter Keys
        ---------------------
        - ``industry`` (str) — filter by Industry master value.
        - ``status``   (str) — filter by Company status field.
        - ``country``  (str) — filter by country.
        - ``state``    (str) — filter by state/region.
        - ``city``     (str) — filter by city.

        Adding New Filters
        ------------------
        Append a new ``if filters.get("<key>"):`` block here.  The API method
        signatures and ``list_companies`` / ``search_companies`` signatures do
        not need to change.

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

        if filters.get("industry"):
            orm["industry"] = filters["industry"]

        if filters.get("status"):
            orm["status"] = filters["status"]

        if filters.get("country"):
            orm["country"] = filters["country"]

        if filters.get("state"):
            orm["state"] = filters["state"]

        if filters.get("city"):
            orm["city"] = filters["city"]

        # TODO: Add company_size filter in a future sprint.
        # if filters.get("company_size"):
        #     orm["company_size"] = filters["company_size"]

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

        Rejects any ``order_by`` value not in ``ALLOWED_SORT_FIELDS`` and falls
        back to ``creation desc`` to prevent malformed queries.

        Parameters
        ----------
        order_by : str
            Requested sort field.
        order_dir : str
            Requested sort direction (``"asc"`` or ``"desc"``).

        Returns
        -------
        str
            A safe ``"field direction"`` string, e.g. ``"company_name asc"``.
        """
        safe_field = order_by if order_by in ALLOWED_SORT_FIELDS else "creation"
        safe_dir = "asc" if str(order_dir).lower() == "asc" else "desc"
        return f"{safe_field} {safe_dir}"
