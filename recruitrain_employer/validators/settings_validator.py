# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.settings_validator
====================================================

Validation logic for all Employer Settings groups.

Groups validated
----------------
- General     : timezone, language, date_format, currency, theme
- Branding    : logo URL, primary_color, secondary_color hex codes
- Notification: boolean preference flags
- Security    : password policy, session_timeout, allowed_domains
- Recruitment : pipeline, interview_duration, boolean flags
- Integration : SMTP, calendar keys, webhook URLs, API keys
- Audit       : boolean flag, retention_days int
"""

from __future__ import annotations

import json
import re
from typing import Any

from recruitrain_employer.utils.exceptions import ATSValidationError

# ---------------------------------------------------------------------------
# Allowed value sets
# ---------------------------------------------------------------------------

_ALLOWED_TIMEZONES = {
    "UTC",
    "Africa/Nairobi",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/New_York",
    "America/Sao_Paulo",
    "America/Toronto",
    "Asia/Bangkok",
    "Asia/Colombo",
    "Asia/Dubai",
    "Asia/Jakarta",
    "Asia/Karachi",
    "Asia/Kolkata",
    "Asia/Kuala_Lumpur",
    "Asia/Manila",
    "Asia/Seoul",
    "Asia/Shanghai",
    "Asia/Singapore",
    "Asia/Taipei",
    "Asia/Tokyo",
    "Australia/Melbourne",
    "Australia/Sydney",
    "Europe/Amsterdam",
    "Europe/Berlin",
    "Europe/Brussels",
    "Europe/Bucharest",
    "Europe/Helsinki",
    "Europe/Istanbul",
    "Europe/Kiev",
    "Europe/Lisbon",
    "Europe/London",
    "Europe/Madrid",
    "Europe/Moscow",
    "Europe/Paris",
    "Europe/Prague",
    "Europe/Rome",
    "Europe/Stockholm",
    "Europe/Warsaw",
    "Europe/Zurich",
    "Pacific/Auckland",
    "Pacific/Honolulu",
}

_ALLOWED_LANGUAGES = {
    "en", "de", "fr", "es", "it", "pt", "nl", "pl", "cs",
    "ro", "hu", "bg", "hr", "sk", "sl", "ar", "zh", "ja",
    "ko", "hi", "id", "tr", "ru", "uk", "vi",
}

_ALLOWED_DATE_FORMATS = {
    "DD-MM-YYYY", "MM-DD-YYYY", "YYYY-MM-DD",
    "DD/MM/YYYY", "MM/DD/YYYY", "DD.MM.YYYY",
}

_ALLOWED_CURRENCIES = {
    "EUR", "USD", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN", "CZK",
    "RON", "HUF", "BGN", "HRK", "INR", "AED", "SGD", "MYR", "THB",
    "PHP", "IDR", "BRL", "CAD", "AUD", "NZD", "JPY", "CNY", "KRW",
    "TRY", "RUB", "ZAR",
}

_ALLOWED_THEMES = {"light", "dark", "system"}

_ALLOWED_PIPELINES = {"Standard", "Fast Track", "Executive", "Technical"}

_ALLOWED_CANDIDATE_SOURCES = {
    "Direct Application", "Job Board", "Referral",
    "Recruitment Agency", "LinkedIn", "Indeed",
    "Glassdoor", "Internal Transfer", "Campus Recruitment", "Other",
}

_ALLOWED_STORAGE_POLICIES = {
    "Frappe Storage", "S3", "Google Cloud Storage", "Azure Blob",
}

_NOTIFICATION_BOOLEAN_KEYS = {
    "new_application_email",
    "new_application_inapp",
    "interview_reminder_email",
    "interview_reminder_inapp",
    "offer_response_email",
    "offer_response_inapp",
    "system_alerts_email",
    "system_alerts_inapp",
    "sms_notifications",
    "application_alerts",
    "offer_alerts",
}

_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")
_URL_RE = re.compile(
    r"^https?://"
    r"(?:(?:[A-Z0-9](?:[A-Z0-9\-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|"
    r"localhost|"
    r"\d{1,3}(?:\.\d{1,3}){3})"
    r"(?::\d+)?(?:/?|[/?]\S+)$",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
_DOMAIN_RE = re.compile(r"^[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

_SESSION_TIMEOUT_MIN = 5
_SESSION_TIMEOUT_MAX = 43200  # 30 days in minutes
_MIN_PASSWORD_LENGTH_MIN = 6
_MIN_PASSWORD_LENGTH_MAX = 128
_INTERVIEW_DURATION_MIN = 15
_INTERVIEW_DURATION_MAX = 480
_REMINDER_DAYS_MIN = 1
_REMINDER_DAYS_MAX = 365
_AUDIT_RETENTION_MIN = 7
_AUDIT_RETENTION_MAX = 3650
_SMTP_PORT_MIN = 1
_SMTP_PORT_MAX = 65535


class SettingsValidator:
    """Validates all settings groups for Employer Settings.

    Usage
    -----
    ::
        SettingsValidator.validate_general(data)
        SettingsValidator.validate_security(data)
        SettingsValidator.validate_integration(data)
    """

    # ------------------------------------------------------------------
    # General Settings
    # ------------------------------------------------------------------

    @staticmethod
    def validate_general(data: dict) -> dict:
        """Validate general settings fields.

        Validates: timezone, language, date_format, currency, theme.
        All fields are optional — only validated when present.

        Returns
        -------
        dict
            Cleaned data dict with only recognized general fields.
        """
        cleaned: dict = {}

        if "timezone" in data:
            tz = str(data["timezone"]).strip()
            if tz not in _ALLOWED_TIMEZONES:
                raise ATSValidationError(
                    f"Invalid timezone '{tz}'.",
                    field="timezone",
                    details={"allowed_sample": sorted(_ALLOWED_TIMEZONES)[:5]},
                )
            cleaned["timezone"] = tz

        if "language" in data:
            lang = str(data["language"]).strip().lower()
            if lang not in _ALLOWED_LANGUAGES:
                raise ATSValidationError(
                    f"Invalid language code '{lang}'.",
                    field="language",
                )
            cleaned["language"] = lang

        if "date_format" in data:
            df = str(data["date_format"]).strip()
            if df not in _ALLOWED_DATE_FORMATS:
                raise ATSValidationError(
                    f"Invalid date format '{df}'.",
                    field="date_format",
                    details={"allowed": sorted(_ALLOWED_DATE_FORMATS)},
                )
            cleaned["date_format"] = df

        if "currency" in data:
            cur = str(data["currency"]).strip().upper()
            if cur not in _ALLOWED_CURRENCIES:
                raise ATSValidationError(
                    f"Invalid currency code '{cur}'.",
                    field="currency",
                )
            cleaned["currency"] = cur

        if "theme" in data:
            theme = str(data["theme"]).strip().lower()
            if theme not in _ALLOWED_THEMES:
                raise ATSValidationError(
                    f"Invalid theme '{theme}'. Must be one of: {sorted(_ALLOWED_THEMES)}.",
                    field="theme",
                )
            cleaned["theme"] = theme

        return cleaned

    # ------------------------------------------------------------------
    # Branding Settings (stored on Company DocType)
    # ------------------------------------------------------------------

    @staticmethod
    def validate_branding(data: dict) -> dict:
        """Validate branding settings.

        Validates: primary_color, secondary_color (hex), logo/banner URLs.
        Color values must be valid CSS hex codes (#RGB or #RRGGBB).
        """
        cleaned: dict = {}

        for color_field in ("primary_color", "secondary_color"):
            if color_field in data and data[color_field]:
                color = str(data[color_field]).strip()
                if not _HEX_COLOR_RE.match(color):
                    raise ATSValidationError(
                        f"'{color_field}' must be a valid hex color (e.g. #FF5733).",
                        field=color_field,
                    )
                cleaned[color_field] = color

        for url_field in ("logo", "banner"):
            if url_field in data and data[url_field]:
                url = str(data[url_field]).strip()
                # Accept both absolute URLs and Frappe-relative paths (/files/...)
                if not url.startswith("/") and not _URL_RE.match(url):
                    raise ATSValidationError(
                        f"'{url_field}' must be a valid URL or Frappe file path.",
                        field=url_field,
                    )
                cleaned[url_field] = url

        return cleaned

    # ------------------------------------------------------------------
    # Notification Settings (stored on Employer User.notification_preferences)
    # ------------------------------------------------------------------

    @staticmethod
    def validate_notification(data: dict) -> dict:
        """Validate notification preference flags.

        All recognized keys must be booleans or boolean-coercible values.
        Unknown keys are silently dropped (forward-compatibility).
        """
        cleaned: dict = {}

        for key in _NOTIFICATION_BOOLEAN_KEYS:
            if key in data:
                val = data[key]
                if isinstance(val, bool):
                    cleaned[key] = val
                elif isinstance(val, int):
                    cleaned[key] = bool(val)
                elif isinstance(val, str) and val.lower() in ("true", "1", "yes"):
                    cleaned[key] = True
                elif isinstance(val, str) and val.lower() in ("false", "0", "no"):
                    cleaned[key] = False
                else:
                    raise ATSValidationError(
                        f"Notification preference '{key}' must be a boolean.",
                        field=key,
                    )

        return cleaned

    # ------------------------------------------------------------------
    # Security Settings
    # ------------------------------------------------------------------

    @staticmethod
    def validate_security(data: dict) -> dict:
        """Validate security settings.

        Validates: password_min_length, session_timeout_minutes,
        enable_two_factor_auth, enable_login_alerts, allowed_domains.
        """
        cleaned: dict = {}

        if "password_min_length" in data:
            try:
                pml = int(data["password_min_length"])
            except (TypeError, ValueError):
                raise ATSValidationError(
                    "password_min_length must be an integer.",
                    field="password_min_length",
                )
            if not (_MIN_PASSWORD_LENGTH_MIN <= pml <= _MIN_PASSWORD_LENGTH_MAX):
                raise ATSValidationError(
                    f"password_min_length must be between "
                    f"{_MIN_PASSWORD_LENGTH_MIN} and {_MIN_PASSWORD_LENGTH_MAX}.",
                    field="password_min_length",
                )
            cleaned["password_min_length"] = pml

        for bool_field in (
            "password_require_uppercase",
            "password_require_number",
            "password_require_special",
            "enable_two_factor_auth",
            "enable_login_alerts",
        ):
            if bool_field in data:
                cleaned[bool_field] = _coerce_bool(bool_field, data[bool_field])

        if "session_timeout_minutes" in data:
            try:
                sto = int(data["session_timeout_minutes"])
            except (TypeError, ValueError):
                raise ATSValidationError(
                    "session_timeout_minutes must be an integer.",
                    field="session_timeout_minutes",
                )
            if not (_SESSION_TIMEOUT_MIN <= sto <= _SESSION_TIMEOUT_MAX):
                raise ATSValidationError(
                    f"session_timeout_minutes must be between "
                    f"{_SESSION_TIMEOUT_MIN} and {_SESSION_TIMEOUT_MAX}.",
                    field="session_timeout_minutes",
                )
            cleaned["session_timeout_minutes"] = sto

        if "allowed_domains" in data and data["allowed_domains"]:
            raw_domains = str(data["allowed_domains"]).strip()
            domains = [d.strip() for d in raw_domains.split(",") if d.strip()]
            invalid = [d for d in domains if not _DOMAIN_RE.match(d)]
            if invalid:
                raise ATSValidationError(
                    f"Invalid domain(s): {invalid}.",
                    field="allowed_domains",
                )
            cleaned["allowed_domains"] = ", ".join(domains)

        return cleaned

    # ------------------------------------------------------------------
    # Recruitment Settings
    # ------------------------------------------------------------------

    @staticmethod
    def validate_recruitment(data: dict) -> dict:
        """Validate recruitment settings.

        Validates: default_hiring_pipeline, default_interview_duration,
        auto_archive_candidates, enable_resume_parsing, default_candidate_source.
        """
        cleaned: dict = {}

        if "default_hiring_pipeline" in data and data["default_hiring_pipeline"]:
            pipeline = str(data["default_hiring_pipeline"]).strip()
            if pipeline not in _ALLOWED_PIPELINES:
                raise ATSValidationError(
                    f"Invalid default_hiring_pipeline '{pipeline}'.",
                    field="default_hiring_pipeline",
                    details={"allowed": sorted(_ALLOWED_PIPELINES)},
                )
            cleaned["default_hiring_pipeline"] = pipeline

        if "default_interview_duration" in data:
            try:
                dur = int(data["default_interview_duration"])
            except (TypeError, ValueError):
                raise ATSValidationError(
                    "default_interview_duration must be an integer.",
                    field="default_interview_duration",
                )
            if not (_INTERVIEW_DURATION_MIN <= dur <= _INTERVIEW_DURATION_MAX):
                raise ATSValidationError(
                    f"default_interview_duration must be between "
                    f"{_INTERVIEW_DURATION_MIN} and {_INTERVIEW_DURATION_MAX} minutes.",
                    field="default_interview_duration",
                )
            cleaned["default_interview_duration"] = dur

        for bool_field in ("auto_archive_candidates", "enable_resume_parsing"):
            if bool_field in data:
                cleaned[bool_field] = _coerce_bool(bool_field, data[bool_field])

        if "default_candidate_source" in data and data["default_candidate_source"]:
            src = str(data["default_candidate_source"]).strip()
            if src not in _ALLOWED_CANDIDATE_SOURCES:
                raise ATSValidationError(
                    f"Invalid default_candidate_source '{src}'.",
                    field="default_candidate_source",
                    details={"allowed": sorted(_ALLOWED_CANDIDATE_SOURCES)},
                )
            cleaned["default_candidate_source"] = src

        return cleaned

    # ------------------------------------------------------------------
    # International Settings
    # ------------------------------------------------------------------

    @staticmethod
    def validate_international(data: dict) -> dict:
        """Validate international / immigration reminder settings."""
        cleaned: dict = {}

        for day_field in ("default_visa_reminder_days", "passport_reminder_days"):
            if day_field in data:
                try:
                    days = int(data[day_field])
                except (TypeError, ValueError):
                    raise ATSValidationError(
                        f"{day_field} must be an integer.",
                        field=day_field,
                    )
                if not (_REMINDER_DAYS_MIN <= days <= _REMINDER_DAYS_MAX):
                    raise ATSValidationError(
                        f"{day_field} must be between "
                        f"{_REMINDER_DAYS_MIN} and {_REMINDER_DAYS_MAX}.",
                        field=day_field,
                    )
                cleaned[day_field] = days

        if "enable_work_permit_reminder" in data:
            cleaned["enable_work_permit_reminder"] = _coerce_bool(
                "enable_work_permit_reminder", data["enable_work_permit_reminder"]
            )

        return cleaned

    # ------------------------------------------------------------------
    # Document Settings
    # ------------------------------------------------------------------

    @staticmethod
    def validate_documents(data: dict) -> dict:
        """Validate document management settings."""
        cleaned: dict = {}

        if "default_document_types" in data and data["default_document_types"]:
            raw = data["default_document_types"]
            if isinstance(raw, list):
                cleaned["default_document_types"] = json.dumps(raw)
            elif isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                    if not isinstance(parsed, list):
                        raise ATSValidationError(
                            "default_document_types must be a JSON array.",
                            field="default_document_types",
                        )
                    cleaned["default_document_types"] = json.dumps(parsed)
                except json.JSONDecodeError:
                    raise ATSValidationError(
                        "default_document_types must be a valid JSON array.",
                        field="default_document_types",
                    )

        if "document_expiry_reminder_days" in data:
            try:
                days = int(data["document_expiry_reminder_days"])
            except (TypeError, ValueError):
                raise ATSValidationError(
                    "document_expiry_reminder_days must be an integer.",
                    field="document_expiry_reminder_days",
                )
            if not (_REMINDER_DAYS_MIN <= days <= _REMINDER_DAYS_MAX):
                raise ATSValidationError(
                    f"document_expiry_reminder_days must be between "
                    f"{_REMINDER_DAYS_MIN} and {_REMINDER_DAYS_MAX}.",
                    field="document_expiry_reminder_days",
                )
            cleaned["document_expiry_reminder_days"] = days

        if "storage_policy" in data and data["storage_policy"]:
            sp = str(data["storage_policy"]).strip()
            if sp not in _ALLOWED_STORAGE_POLICIES:
                raise ATSValidationError(
                    f"Invalid storage_policy '{sp}'.",
                    field="storage_policy",
                    details={"allowed": sorted(_ALLOWED_STORAGE_POLICIES)},
                )
            cleaned["storage_policy"] = sp

        return cleaned

    # ------------------------------------------------------------------
    # Integration Settings
    # ------------------------------------------------------------------

    @staticmethod
    def validate_integration(data: dict) -> dict:
        """Validate integration settings.

        Validates: SMTP host/port/username, webhook URLs, API keys JSON object.
        Sensitive fields (passwords, secrets) are accepted as-is — storage
        security is the responsibility of Frappe's Password field type.
        """
        cleaned: dict = {}

        if "smtp_host" in data and data["smtp_host"]:
            host = str(data["smtp_host"]).strip()
            if not host:
                raise ATSValidationError("smtp_host cannot be empty.", field="smtp_host")
            cleaned["smtp_host"] = host

        if "smtp_port" in data:
            try:
                port = int(data["smtp_port"])
            except (TypeError, ValueError):
                raise ATSValidationError(
                    "smtp_port must be an integer.", field="smtp_port"
                )
            if not (_SMTP_PORT_MIN <= port <= _SMTP_PORT_MAX):
                raise ATSValidationError(
                    f"smtp_port must be between {_SMTP_PORT_MIN} and {_SMTP_PORT_MAX}.",
                    field="smtp_port",
                )
            cleaned["smtp_port"] = port

        if "smtp_username" in data and data["smtp_username"]:
            uname = str(data["smtp_username"]).strip()
            if not _EMAIL_RE.match(uname) and "@" not in uname:
                raise ATSValidationError(
                    "smtp_username must be a valid email address.",
                    field="smtp_username",
                )
            cleaned["smtp_username"] = uname

        for bool_field in (
            "smtp_use_tls",
            "google_calendar_enabled",
            "microsoft_calendar_enabled",
            "zoom_enabled",
            "teams_enabled",
        ):
            if bool_field in data:
                cleaned[bool_field] = _coerce_bool(bool_field, data[bool_field])

        for str_field in (
            "google_calendar_client_id",
            "microsoft_tenant_id",
            "microsoft_client_id",
            "zoom_api_key",
            "smtp_password",
            "google_calendar_client_secret",
            "microsoft_client_secret",
            "zoom_api_secret",
        ):
            if str_field in data and data[str_field]:
                cleaned[str_field] = str(data[str_field]).strip()

        if "teams_webhook_url" in data and data["teams_webhook_url"]:
            url = str(data["teams_webhook_url"]).strip()
            if not _URL_RE.match(url):
                raise ATSValidationError(
                    "teams_webhook_url must be a valid HTTPS URL.",
                    field="teams_webhook_url",
                )
            cleaned["teams_webhook_url"] = url

        if "webhook_urls" in data and data["webhook_urls"]:
            raw = data["webhook_urls"]
            if isinstance(raw, list):
                for idx, wu in enumerate(raw):
                    if not _URL_RE.match(str(wu)):
                        raise ATSValidationError(
                            f"webhook_urls[{idx}] '{wu}' is not a valid URL.",
                            field="webhook_urls",
                        )
                cleaned["webhook_urls"] = json.dumps(raw)
            elif isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                    if not isinstance(parsed, list):
                        raise ATSValidationError(
                            "webhook_urls must be a JSON array of URLs.",
                            field="webhook_urls",
                        )
                    for idx, wu in enumerate(parsed):
                        if not _URL_RE.match(str(wu)):
                            raise ATSValidationError(
                                f"webhook_urls[{idx}] '{wu}' is not a valid URL.",
                                field="webhook_urls",
                            )
                    cleaned["webhook_urls"] = json.dumps(parsed)
                except json.JSONDecodeError:
                    raise ATSValidationError(
                        "webhook_urls must be a valid JSON array.",
                        field="webhook_urls",
                    )

        if "api_keys" in data and data["api_keys"]:
            raw = data["api_keys"]
            if isinstance(raw, dict):
                cleaned["api_keys"] = json.dumps(raw)
            elif isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                    if not isinstance(parsed, dict):
                        raise ATSValidationError(
                            "api_keys must be a JSON object.",
                            field="api_keys",
                        )
                    cleaned["api_keys"] = json.dumps(parsed)
                except json.JSONDecodeError:
                    raise ATSValidationError(
                        "api_keys must be a valid JSON object.",
                        field="api_keys",
                    )

        return cleaned

    # ------------------------------------------------------------------
    # Audit Settings
    # ------------------------------------------------------------------

    @staticmethod
    def validate_audit(data: dict) -> dict:
        """Validate audit settings."""
        cleaned: dict = {}

        if "audit_log_enabled" in data:
            cleaned["audit_log_enabled"] = _coerce_bool(
                "audit_log_enabled", data["audit_log_enabled"]
            )

        if "audit_retention_days" in data:
            try:
                days = int(data["audit_retention_days"])
            except (TypeError, ValueError):
                raise ATSValidationError(
                    "audit_retention_days must be an integer.",
                    field="audit_retention_days",
                )
            if not (_AUDIT_RETENTION_MIN <= days <= _AUDIT_RETENTION_MAX):
                raise ATSValidationError(
                    f"audit_retention_days must be between "
                    f"{_AUDIT_RETENTION_MIN} and {_AUDIT_RETENTION_MAX}.",
                    field="audit_retention_days",
                )
            cleaned["audit_retention_days"] = days

        return cleaned


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _coerce_bool(field: str, value: Any) -> bool:
    """Coerce a value to bool or raise ATSValidationError."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        if value.lower() in ("true", "1", "yes"):
            return True
        if value.lower() in ("false", "0", "no"):
            return False
    raise ATSValidationError(
        f"Field '{field}' must be a boolean.",
        field=field,
    )
