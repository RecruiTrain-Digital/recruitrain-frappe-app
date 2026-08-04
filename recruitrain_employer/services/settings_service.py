# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.services.settings_service
================================================

Employer Settings Business Logic Service.

Architecture
------------
All database operations for Employer Settings are centralised here.
The API layer (``recruitrain_employer.api.settings``) must not access
``frappe.get_doc``, ``frappe.get_all``, or ``frappe.db`` directly.

Storage Mapping
---------------
Settings are stored in three canonical locations:

1. **Company DocType** — General (timezone, language, currency, date_format,
   theme) and Branding (logo, banner, primary_color, secondary_color) fields.
   These already exist in company.json.

2. **Employer User.notification_preferences** (JSON Code field) — Per-user
   notification preference toggles. Already supported by NotificationService.

3. **Employer Settings DocType** (new, company-scoped) — Security, Recruitment,
   International, Documents, Integrations, and Audit settings.

Request/Response Flow::

    React
      │
      ▼
    api/settings.py          ← Parse input, invoke service, format response
      │
      ▼
    SettingsService           ← Business logic, ORM queries
      │
      ▼
    SettingsValidator         ← Per-group field validation
      │
      ▼
    Frappe ORM / MariaDB

Company Isolation
-----------------
Every method that reads or writes settings resolves the company from the
session (via ``get_current_company()``). No cross-company data access
is possible through this service.

Security
--------
- Passwords / secrets are stored in Frappe Password fields — encrypted at rest.
- API keys are stored as a JSON object in a Small Text field — treat as
  sensitive, never log their values.
- No raw SQL queries — only ``frappe.get_doc``, ``frappe.db.set_value``,
  and ``frappe.db.get_value`` are used.
"""

from __future__ import annotations

import json
from typing import Any

import frappe

from recruitrain_employer.utils.constants import (
    DEFAULT_NOTIFICATION_PREFERENCES,
    DOCTYPE_COMPANY,
    DOCTYPE_EMPLOYER_USER,
)
from recruitrain_employer.utils.exceptions import (
    ATSNotFoundError,
    ATSValidationError,
)
from recruitrain_employer.validators.settings_validator import SettingsValidator

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

DOCTYPE_EMPLOYER_SETTINGS = "Employer Settings"

#: Fields on Company DocType that belong to the General settings group.
_COMPANY_GENERAL_FIELDS = [
    "timezone",
    "language",
    "date_format",
    "currency",
    "theme",
]

#: Fields on Company DocType that belong to the Branding settings group.
_COMPANY_BRANDING_FIELDS = [
    "logo",
    "banner",
    "primary_color",
    "secondary_color",
    "company_name",
    "email",
]

#: Fields on Employer Settings DocType for Security group.
_SECURITY_FIELDS = [
    "password_min_length",
    "password_require_uppercase",
    "password_require_number",
    "password_require_special",
    "session_timeout_minutes",
    "enable_two_factor_auth",
    "enable_login_alerts",
    "allowed_domains",
]

#: Fields on Employer Settings DocType for Recruitment group.
_RECRUITMENT_FIELDS = [
    "default_hiring_pipeline",
    "default_interview_duration",
    "auto_archive_candidates",
    "enable_resume_parsing",
    "default_candidate_source",
]

#: Fields on Employer Settings DocType for International group.
_INTERNATIONAL_FIELDS = [
    "default_visa_reminder_days",
    "passport_reminder_days",
    "enable_work_permit_reminder",
]

#: Fields on Employer Settings DocType for Documents group.
_DOCUMENT_FIELDS = [
    "default_document_types",
    "document_expiry_reminder_days",
    "storage_policy",
]

#: Fields on Employer Settings DocType for Integration group.
#: NOTE: password/secret fields are handled separately via get_password().
_INTEGRATION_FIELDS = [
    "smtp_host",
    "smtp_port",
    "smtp_username",
    "smtp_use_tls",
    "google_calendar_enabled",
    "google_calendar_client_id",
    "microsoft_calendar_enabled",
    "microsoft_tenant_id",
    "microsoft_client_id",
    "zoom_enabled",
    "zoom_api_key",
    "teams_enabled",
    "teams_webhook_url",
    "webhook_urls",
]

#: Integration fields that are encrypted (Password fieldtype). Their values
#: are retrieved via doc.get_password() — never returned to API consumers.
_ENCRYPTED_INTEGRATION_FIELDS = [
    "smtp_password",
    "google_calendar_client_secret",
    "microsoft_client_secret",
    "zoom_api_secret",
]

#: Fields on Employer Settings DocType for Audit group.
_AUDIT_FIELDS = [
    "audit_log_enabled",
    "audit_retention_days",
]


# ---------------------------------------------------------------------------
# Service Class
# ---------------------------------------------------------------------------


class SettingsService:
    """Encapsulates all business logic for Employer Settings operations.

    All database reads and writes for the Settings domain go through this class.
    No DocType access is permitted in the API layer.

    Usage
    -----
    ::
        service = SettingsService()
        data = service.get_settings(company_id="RecruiTrain")
    """

    def __init__(self) -> None:
        self._validator = SettingsValidator()

    # ------------------------------------------------------------------
    # Aggregate Settings (all groups in one response)
    # ------------------------------------------------------------------

    def get_settings(self, company_id: str) -> dict:
        """Return all settings groups for the company in a single response.

        Assembles General, Branding, Notification, Security, Recruitment,
        International, Documents, Integration, and Audit settings from
        their canonical storage locations.

        Parameters
        ----------
        company_id : str
            The ``name`` field of the Company record.

        Returns
        -------
        dict
            Combined settings payload grouped by category.

        Raises
        ------
        ATSNotFoundError
            If the Company record does not exist.
        """
        self._assert_company_exists(company_id)
        return {
            "general": self._get_general(company_id),
            "branding": self._get_branding(company_id),
            "notification": self._get_notification(company_id),
            "security": self._get_security(company_id),
            "recruitment": self._get_recruitment(company_id),
            "international": self._get_international(company_id),
            "documents": self._get_documents(company_id),
            "integration": self._get_integration(company_id),
            "audit": self._get_audit(company_id),
        }

    def update_settings(self, company_id: str, data: dict) -> dict:
        """Apply a partial update to any settings group(s) for the company.

        Dispatches sub-dicts to the appropriate per-group update methods.
        Only the groups present in ``data`` are updated.

        Parameters
        ----------
        company_id : str
            The ``name`` field of the Company record.
        data : dict
            A dict whose keys are group names (``general``, ``branding``,
            ``notification``, ``security``, ``recruitment``, ``integration``,
            ``audit``) and whose values are the group-specific payload dicts.

        Returns
        -------
        dict
            The complete updated settings payload.

        Raises
        ------
        ATSNotFoundError
            If the Company record does not exist.
        ATSValidationError
            If any field value fails validation.
        """
        self._assert_company_exists(company_id)

        if "general" in data:
            self.update_general_settings(company_id, data["general"])
        if "branding" in data:
            self.update_branding_settings(company_id, data["branding"])
        if "notification" in data:
            self.update_notification_settings(company_id, data["notification"])
        if "security" in data:
            self.update_security_settings(company_id, data["security"])
        if "recruitment" in data:
            self.update_recruitment_settings(company_id, data["recruitment"])
        if "international" in data:
            self._update_employer_settings_fields(
                company_id,
                SettingsValidator.validate_international(data["international"]),
            )
        if "documents" in data:
            self._update_employer_settings_fields(
                company_id,
                SettingsValidator.validate_documents(data["documents"]),
            )
        if "integration" in data:
            self.update_integration_settings(company_id, data["integration"])
        if "audit" in data:
            self._update_employer_settings_fields(
                company_id,
                SettingsValidator.validate_audit(data["audit"]),
            )

        return self.get_settings(company_id)

    # ------------------------------------------------------------------
    # General Settings
    # ------------------------------------------------------------------

    def get_general_settings(self, company_id: str) -> dict:
        """Return general settings (timezone, language, currency, etc.).

        Data is read from the Company DocType.
        """
        self._assert_company_exists(company_id)
        return self._get_general(company_id)

    def update_general_settings(self, company_id: str, data: dict) -> dict:
        """Update general settings on the Company DocType.

        Parameters
        ----------
        company_id : str
            The ``name`` of the Company to update.
        data : dict
            General settings fields to update.

        Returns
        -------
        dict
            Updated general settings.
        """
        self._assert_company_exists(company_id)
        cleaned = SettingsValidator.validate_general(data)
        if cleaned:
            self._update_company_fields(company_id, cleaned)
        return self._get_general(company_id)

    # ------------------------------------------------------------------
    # Branding Settings
    # ------------------------------------------------------------------

    def get_branding_settings(self, company_id: str) -> dict:
        """Return branding settings (logo, banner, colors) from Company DocType."""
        self._assert_company_exists(company_id)
        return self._get_branding(company_id)

    def update_branding_settings(self, company_id: str, data: dict) -> dict:
        """Update branding settings on the Company DocType.

        Parameters
        ----------
        company_id : str
            The ``name`` of the Company.
        data : dict
            Branding fields: primary_color, secondary_color, logo, banner.

        Returns
        -------
        dict
            Updated branding settings.
        """
        self._assert_company_exists(company_id)
        cleaned = SettingsValidator.validate_branding(data)
        if cleaned:
            self._update_company_fields(company_id, cleaned)
        return self._get_branding(company_id)

    # ------------------------------------------------------------------
    # Notification Settings
    # ------------------------------------------------------------------

    def get_notification_settings(self, company_id: str, user: str) -> dict:
        """Return notification preferences for the specified user.

        Data is read from ``Employer User.notification_preferences`` JSON field.

        Parameters
        ----------
        company_id : str
            Company context for scoping.
        user : str
            The Frappe User (email) whose preferences to fetch.

        Returns
        -------
        dict
            Notification preference flags merged with defaults.
        """
        self._assert_company_exists(company_id)
        from recruitrain_employer.services.notification_service import (
            NotificationService,
        )
        ns = NotificationService()
        return ns.get_notification_preferences(user=user, company=company_id)

    def update_notification_settings(
        self, company_id: str, user: str, data: dict
    ) -> dict:
        """Update notification preferences for the specified user.

        Delegates to ``NotificationService.update_notification_preferences``
        which writes to ``Employer User.notification_preferences``.

        Parameters
        ----------
        company_id : str
            Company context for scoping.
        user : str
            The Frappe User (email) whose preferences to update.
        data : dict
            Notification preference flags (booleans).

        Returns
        -------
        dict
            The fully merged, updated notification preferences.
        """
        self._assert_company_exists(company_id)
        cleaned = SettingsValidator.validate_notification(data)
        from recruitrain_employer.services.notification_service import (
            NotificationService,
        )
        ns = NotificationService()
        return ns.update_notification_preferences(
            user=user,
            company=company_id,
            raw_preferences=cleaned,
        )

    # ------------------------------------------------------------------
    # Security Settings
    # ------------------------------------------------------------------

    def get_security_settings(self, company_id: str) -> dict:
        """Return security settings from Employer Settings DocType."""
        self._assert_company_exists(company_id)
        return self._get_security(company_id)

    def update_security_settings(self, company_id: str, data: dict) -> dict:
        """Update security settings on the Employer Settings DocType.

        Parameters
        ----------
        company_id : str
            The company whose settings to update.
        data : dict
            Security fields to update.

        Returns
        -------
        dict
            Updated security settings.
        """
        self._assert_company_exists(company_id)
        cleaned = SettingsValidator.validate_security(data)
        if cleaned:
            self._update_employer_settings_fields(company_id, cleaned)
        return self._get_security(company_id)

    # ------------------------------------------------------------------
    # Recruitment Settings
    # ------------------------------------------------------------------

    def get_recruitment_settings(self, company_id: str) -> dict:
        """Return recruitment configuration from Employer Settings DocType."""
        self._assert_company_exists(company_id)
        return self._get_recruitment(company_id)

    def update_recruitment_settings(self, company_id: str, data: dict) -> dict:
        """Update recruitment settings on the Employer Settings DocType.

        Parameters
        ----------
        company_id : str
            The company whose settings to update.
        data : dict
            Recruitment fields to update.

        Returns
        -------
        dict
            Updated recruitment settings.
        """
        self._assert_company_exists(company_id)
        cleaned = SettingsValidator.validate_recruitment(data)
        if cleaned:
            self._update_employer_settings_fields(company_id, cleaned)
        return self._get_recruitment(company_id)

    # ------------------------------------------------------------------
    # Integration Settings
    # ------------------------------------------------------------------

    def get_integration_settings(self, company_id: str) -> dict:
        """Return integration settings from Employer Settings DocType.

        Encrypted fields (passwords, secrets) are masked and excluded from
        the response. Only a boolean ``{field}_configured`` flag is returned
        indicating whether the secret has been set.
        """
        self._assert_company_exists(company_id)
        return self._get_integration(company_id)

    def update_integration_settings(self, company_id: str, data: dict) -> dict:
        """Update integration settings on the Employer Settings DocType.

        Handles both plain fields and encrypted Password fields.

        Parameters
        ----------
        company_id : str
            The company whose settings to update.
        data : dict
            Integration fields to update.

        Returns
        -------
        dict
            Updated integration settings (with secrets masked).
        """
        self._assert_company_exists(company_id)
        cleaned = SettingsValidator.validate_integration(data)
        if cleaned:
            # Split out encrypted fields — they must be set on the doc, not via db.set_value
            encrypted = {
                k: cleaned.pop(k)
                for k in list(cleaned.keys())
                if k in _ENCRYPTED_INTEGRATION_FIELDS
            }
            # Write non-encrypted fields
            if cleaned:
                self._update_employer_settings_fields(company_id, cleaned)
            # Write encrypted fields through the doc save to ensure hashing
            if encrypted:
                self._update_employer_settings_encrypted(company_id, encrypted)

        return self._get_integration(company_id)

    # ------------------------------------------------------------------
    # Private: Group Readers
    # ------------------------------------------------------------------

    def _get_general(self, company_id: str) -> dict:
        """Read General settings from the Company DocType."""
        doc = self._get_company_doc(company_id)
        return {field: doc.get(field) for field in _COMPANY_GENERAL_FIELDS}

    def _get_branding(self, company_id: str) -> dict:
        """Read Branding settings from the Company DocType."""
        doc = self._get_company_doc(company_id)
        return {field: doc.get(field) for field in _COMPANY_BRANDING_FIELDS}

    def _get_notification(self, company_id: str) -> dict:
        """Read Notification settings — returns defaults merged with stored prefs.

        company_id is used for scoping only; preferences are per-user.
        Returns the defaults here since this is the company-level view.
        """
        return dict(DEFAULT_NOTIFICATION_PREFERENCES)

    def _get_security(self, company_id: str) -> dict:
        """Read Security settings from the Employer Settings DocType."""
        doc = self._get_or_create_settings(company_id)
        return {field: doc.get(field) for field in _SECURITY_FIELDS}

    def _get_recruitment(self, company_id: str) -> dict:
        """Read Recruitment settings from the Employer Settings DocType."""
        doc = self._get_or_create_settings(company_id)
        result = {field: doc.get(field) for field in _RECRUITMENT_FIELDS}
        return result

    def _get_international(self, company_id: str) -> dict:
        """Read International settings from the Employer Settings DocType."""
        doc = self._get_or_create_settings(company_id)
        return {field: doc.get(field) for field in _INTERNATIONAL_FIELDS}

    def _get_documents(self, company_id: str) -> dict:
        """Read Documents settings from the Employer Settings DocType."""
        doc = self._get_or_create_settings(company_id)
        result = {field: doc.get(field) for field in _DOCUMENT_FIELDS}
        # Deserialize JSON array field for API consumers
        raw = result.get("default_document_types")
        if raw and isinstance(raw, str):
            try:
                result["default_document_types"] = json.loads(raw)
            except json.JSONDecodeError:
                result["default_document_types"] = []
        return result

    def _get_integration(self, company_id: str) -> dict:
        """Read Integration settings from the Employer Settings DocType.

        Encrypted secret fields are replaced with a boolean ``{field}_configured``
        flag to avoid leaking credentials through the API.
        """
        doc = self._get_or_create_settings(company_id)
        result = {field: doc.get(field) for field in _INTEGRATION_FIELDS}

        # Deserialize JSON fields
        for json_field in ("webhook_urls", "api_keys"):
            raw = result.get(json_field)
            if raw and isinstance(raw, str):
                try:
                    result[json_field] = json.loads(raw)
                except json.JSONDecodeError:
                    result[json_field] = [] if json_field == "webhook_urls" else {}

        # Mask encrypted fields — only expose whether they are configured
        for enc_field in _ENCRYPTED_INTEGRATION_FIELDS:
            try:
                secret = doc.get_password(enc_field, raise_exception=False)
                result[f"{enc_field}_configured"] = bool(secret)
            except Exception:
                result[f"{enc_field}_configured"] = False

        return result

    def _get_audit(self, company_id: str) -> dict:
        """Read Audit settings from the Employer Settings DocType."""
        doc = self._get_or_create_settings(company_id)
        return {field: doc.get(field) for field in _AUDIT_FIELDS}

    # ------------------------------------------------------------------
    # Private: ORM Helpers
    # ------------------------------------------------------------------

    def _get_company_doc(self, company_id: str):
        """Fetch the Company document or raise ATSNotFoundError."""
        if not frappe.db.exists(DOCTYPE_COMPANY, company_id):
            raise ATSNotFoundError(
                f"Company '{company_id}' was not found.",
                doctype=DOCTYPE_COMPANY,
                name=company_id,
            )
        return frappe.get_doc(DOCTYPE_COMPANY, company_id)

    def _get_or_create_settings(self, company_id: str):
        """Fetch the Employer Settings doc for this company, creating it if absent.

        Employer Settings is created on first access so that new companies
        get default values without requiring manual setup.
        """
        if not frappe.db.exists(DOCTYPE_EMPLOYER_SETTINGS, {"company": company_id}):
            doc = frappe.new_doc(DOCTYPE_EMPLOYER_SETTINGS)
            doc.company = company_id
            doc.insert(ignore_permissions=True)
            return doc

        name = frappe.db.get_value(
            DOCTYPE_EMPLOYER_SETTINGS,
            {"company": company_id},
            "name",
        )
        return frappe.get_doc(DOCTYPE_EMPLOYER_SETTINGS, name)

    def _assert_company_exists(self, company_id: str) -> None:
        """Raise ATSValidationError if company_id is empty, ATSNotFoundError if not found."""
        if not company_id:
            raise ATSValidationError("company_id is required.", field="company_id")
        if not frappe.db.exists(DOCTYPE_COMPANY, company_id):
            raise ATSNotFoundError(
                f"Company '{company_id}' was not found.",
                doctype=DOCTYPE_COMPANY,
                name=company_id,
            )

    def _update_company_fields(self, company_id: str, fields: dict) -> None:
        """Apply field updates to the Company DocType using db.set_value for efficiency."""
        if not fields:
            return
        frappe.db.set_value(
            DOCTYPE_COMPANY,
            company_id,
            fields,
        )

    def _update_employer_settings_fields(
        self, company_id: str, fields: dict
    ) -> None:
        """Apply field updates to the Employer Settings DocType using db.set_value."""
        if not fields:
            return
        doc = self._get_or_create_settings(company_id)
        frappe.db.set_value(
            DOCTYPE_EMPLOYER_SETTINGS,
            doc.name,
            fields,
        )

    def _update_employer_settings_encrypted(
        self, company_id: str, encrypted_fields: dict
    ) -> None:
        """Write encrypted (Password fieldtype) fields via doc.save() for hashing.

        Frappe's Password field type uses bcrypt hashing on save().
        Using db.set_value() bypasses this — we must use the document API.
        """
        doc = self._get_or_create_settings(company_id)
        for field, value in encrypted_fields.items():
            setattr(doc, field, value)
        doc.save(ignore_permissions=True)
