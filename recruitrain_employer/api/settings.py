# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api.settings
===================================

Employer Settings API Endpoints.

Architecture
------------
This module is a **thin controller only**.  The following are strictly
prohibited here:

- ``frappe.get_doc()``
- ``frappe.get_all()``
- ``frappe.get_list()``
- ``frappe.db.*``
- Any direct DocType or ORM access

All business logic and database interactions live in ``SettingsService``.

Endpoint Path Prefix
---------------------
/api/method/recruitrain_employer.api.settings.<function_name>

Response Format
---------------
Success::

    { "success": true, "data": { ... } }

Error::

    { "success": false, "error": { "code": "...", "message": "..." } }

RBAC
----
- All GET endpoints require an active Employer User session.
- POST/update endpoints for Security and Integrations additionally
  require the ``Administrator`` role to prevent privilege escalation.
- Notification preferences require only the current authenticated user.
"""

from __future__ import annotations

import frappe

from recruitrain_employer.services.settings_service import SettingsService
from recruitrain_employer.utils.exceptions import ATSException
from recruitrain_employer.utils.permissions import (
    get_current_company,
    get_current_employer_user,
    require_role,
)
from recruitrain_employer.utils.response import error_response, success_response

# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

_FRAPPE_INTERNAL_KEYS = frozenset(["cmd", "csrf_token", "doctype", "docname"])


def _handle_exc(exc: ATSException) -> dict:
    return error_response(code=exc.code, message=exc.message, details=exc.details)


def _extract_json_body() -> dict:
    """Extract clean JSON body from form_dict, stripping Frappe internals."""
    return {
        k: v
        for k, v in frappe.form_dict.items()
        if k not in _FRAPPE_INTERNAL_KEYS and v not in (None, "")
    }


# ---------------------------------------------------------------------------
# Aggregate Endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_settings() -> dict:
    """Return all settings groups for the authenticated employer's company.

    Returns
    -------
    dict
        ::

            {
                "success": true,
                "data": {
                    "general": { ... },
                    "branding": { ... },
                    "notification": { ... },
                    "security": { ... },
                    "recruitment": { ... },
                    "international": { ... },
                    "documents": { ... },
                    "integration": { ... },
                    "audit": { ... }
                }
            }
    """
    try:
        company_id = get_current_company()
        service = SettingsService()
        settings = service.get_settings(company_id=company_id)
        return success_response(data=settings)
    except ATSException as exc:
        return _handle_exc(exc)


@frappe.whitelist()
def update_settings() -> dict:
    """Update one or more settings groups for the authenticated employer's company.

    Expected Request Body (JSON)
    ----------------------------
    Any combination of settings group keys::

        {
            "general": { "timezone": "Europe/Berlin", "currency": "EUR" },
            "security": { "session_timeout_minutes": 240 }
        }

    Only groups included in the body are updated.

    Returns
    -------
    dict
        The complete updated settings payload.
    """
    try:
        get_current_employer_user()  # Ensure authenticated
        company_id = get_current_company()
        data = _extract_json_body()
        service = SettingsService()
        settings = service.update_settings(company_id=company_id, data=data)
        return success_response(data=settings, message="Settings updated successfully.")
    except ATSException as exc:
        return _handle_exc(exc)


# ---------------------------------------------------------------------------
# General Settings
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_general_settings() -> dict:
    """Return general settings (timezone, language, currency, theme, date_format).

    Returns
    -------
    dict
        Success response with general settings fields.
    """
    try:
        company_id = get_current_company()
        service = SettingsService()
        data = service.get_general_settings(company_id=company_id)
        return success_response(data=data)
    except ATSException as exc:
        return _handle_exc(exc)


@frappe.whitelist()
def update_general_settings() -> dict:
    """Update general settings for the authenticated employer's company.

    Expected Request Body
    ---------------------
    ::

        {
            "timezone": "Europe/Berlin",
            "language": "de",
            "currency": "EUR",
            "date_format": "DD.MM.YYYY",
            "theme": "dark"
        }

    All fields are optional. Only provided fields are updated.

    Returns
    -------
    dict
        Updated general settings.
    """
    try:
        get_current_employer_user()
        company_id = get_current_company()
        data = _extract_json_body()
        service = SettingsService()
        result = service.update_general_settings(company_id=company_id, data=data)
        return success_response(data=result, message="General settings updated.")
    except ATSException as exc:
        return _handle_exc(exc)


# ---------------------------------------------------------------------------
# Branding Settings
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_branding_settings() -> dict:
    """Return branding settings (logo, banner, primary_color, secondary_color).

    Returns
    -------
    dict
        Success response with branding fields from the Company DocType.
    """
    try:
        company_id = get_current_company()
        service = SettingsService()
        data = service.get_branding_settings(company_id=company_id)
        return success_response(data=data)
    except ATSException as exc:
        return _handle_exc(exc)


@frappe.whitelist()
def update_branding_settings() -> dict:
    """Update branding settings for the authenticated employer's company.

    Expected Request Body
    ---------------------
    ::

        {
            "primary_color": "#1A73E8",
            "secondary_color": "#FBBC04",
            "logo": "/files/company_logo.png",
            "banner": "/files/company_banner.png"
        }

    Returns
    -------
    dict
        Updated branding settings.
    """
    try:
        get_current_employer_user()
        company_id = get_current_company()
        data = _extract_json_body()
        service = SettingsService()
        result = service.update_branding_settings(company_id=company_id, data=data)
        return success_response(data=result, message="Branding settings updated.")
    except ATSException as exc:
        return _handle_exc(exc)


# ---------------------------------------------------------------------------
# Notification Settings
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_notification_settings() -> dict:
    """Return notification preferences for the currently authenticated user.

    Notification preferences are stored per-user on ``Employer User.notification_preferences``.
    Returns the user's stored preferences merged with system defaults.

    Returns
    -------
    dict
        Notification preference flags (all booleans).
    """
    try:
        company_id = get_current_company()
        user = getattr(frappe.session, "user", None)
        if not user or user == "Guest":
            from recruitrain_employer.utils.exceptions import ATSPermissionError
            raise ATSPermissionError("Authentication required.")
        service = SettingsService()
        data = service.get_notification_settings(company_id=company_id, user=user)
        return success_response(data=data)
    except ATSException as exc:
        return _handle_exc(exc)


@frappe.whitelist()
def update_notification_settings() -> dict:
    """Update notification preferences for the currently authenticated user.

    Expected Request Body
    ---------------------
    ::

        {
            "new_application_email": true,
            "new_application_inapp": true,
            "interview_reminder_email": false,
            "offer_response_email": true
        }

    Returns
    -------
    dict
        The fully merged, updated notification preferences.
    """
    try:
        company_id = get_current_company()
        user = getattr(frappe.session, "user", None)
        if not user or user == "Guest":
            from recruitrain_employer.utils.exceptions import ATSPermissionError
            raise ATSPermissionError("Authentication required.")
        data = _extract_json_body()
        service = SettingsService()
        result = service.update_notification_settings(
            company_id=company_id, user=user, data=data
        )
        return success_response(data=result, message="Notification preferences updated.")
    except ATSException as exc:
        return _handle_exc(exc)


# ---------------------------------------------------------------------------
# Security Settings
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_security_settings() -> dict:
    """Return security settings for the authenticated employer's company.

    Requires: any authenticated Employer User.

    Returns
    -------
    dict
        Security configuration fields.
    """
    try:
        company_id = get_current_company()
        service = SettingsService()
        data = service.get_security_settings(company_id=company_id)
        return success_response(data=data)
    except ATSException as exc:
        return _handle_exc(exc)


@frappe.whitelist()
def update_security_settings() -> dict:
    """Update security settings. Requires Administrator role.

    Expected Request Body
    ---------------------
    ::

        {
            "password_min_length": 10,
            "password_require_uppercase": true,
            "password_require_number": true,
            "password_require_special": false,
            "session_timeout_minutes": 240,
            "enable_two_factor_auth": false,
            "enable_login_alerts": true,
            "allowed_domains": "acme.com, acme.de"
        }

    Returns
    -------
    dict
        Updated security settings.
    """
    try:
        require_role("Administrator")
        company_id = get_current_company()
        data = _extract_json_body()
        service = SettingsService()
        result = service.update_security_settings(company_id=company_id, data=data)
        return success_response(data=result, message="Security settings updated.")
    except ATSException as exc:
        return _handle_exc(exc)


# ---------------------------------------------------------------------------
# Recruitment Settings
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_recruitment_settings() -> dict:
    """Return recruitment configuration settings.

    Returns
    -------
    dict
        Recruitment configuration fields from Employer Settings.
    """
    try:
        company_id = get_current_company()
        service = SettingsService()
        data = service.get_recruitment_settings(company_id=company_id)
        return success_response(data=data)
    except ATSException as exc:
        return _handle_exc(exc)


@frappe.whitelist()
def update_recruitment_settings() -> dict:
    """Update recruitment settings. Requires HR Manager role or above.

    Expected Request Body
    ---------------------
    ::

        {
            "default_hiring_pipeline": "Standard",
            "default_interview_duration": 60,
            "auto_archive_candidates": false,
            "enable_resume_parsing": true,
            "default_candidate_source": "Job Board"
        }

    Returns
    -------
    dict
        Updated recruitment settings.
    """
    try:
        require_role("HR Manager")
        company_id = get_current_company()
        data = _extract_json_body()
        service = SettingsService()
        result = service.update_recruitment_settings(company_id=company_id, data=data)
        return success_response(data=result, message="Recruitment settings updated.")
    except ATSException as exc:
        return _handle_exc(exc)


# ---------------------------------------------------------------------------
# Integration Settings
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_integration_settings() -> dict:
    """Return integration settings (SMTP, calendar, Zoom, Teams, webhooks).

    Encrypted secrets are not returned — only boolean ``{field}_configured``
    flags indicate whether a secret has been set.

    Returns
    -------
    dict
        Integration configuration (secrets masked).
    """
    try:
        require_role("Administrator")
        company_id = get_current_company()
        service = SettingsService()
        data = service.get_integration_settings(company_id=company_id)
        return success_response(data=data)
    except ATSException as exc:
        return _handle_exc(exc)


@frappe.whitelist()
def update_integration_settings() -> dict:
    """Update integration settings. Requires Administrator role.

    Expected Request Body
    ---------------------
    ::

        {
            "smtp_host": "smtp.sendgrid.net",
            "smtp_port": 587,
            "smtp_username": "apikey@sendgrid.net",
            "smtp_password": "SG.secret...",
            "smtp_use_tls": true,
            "google_calendar_enabled": true,
            "google_calendar_client_id": "...",
            "google_calendar_client_secret": "...",
            "webhook_urls": ["https://hooks.example.com/ats"],
            "api_keys": { "internal_key": "..." }
        }

    Returns
    -------
    dict
        Updated integration settings with secrets masked.
    """
    try:
        require_role("Administrator")
        company_id = get_current_company()
        data = _extract_json_body()
        service = SettingsService()
        result = service.update_integration_settings(company_id=company_id, data=data)
        return success_response(data=result, message="Integration settings updated.")
    except ATSException as exc:
        return _handle_exc(exc)
