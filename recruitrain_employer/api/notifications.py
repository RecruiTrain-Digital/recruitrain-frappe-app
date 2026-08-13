# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api.notifications
=========================================

In-App Notification API Endpoints.

Provides REST endpoints for managing Notification DocType records including:
- Listing and filtering notifications
- Reading single notification
- Marking notification(s) as read
- Deleting and clearing notifications
- Fetching notification counts and stats
- Managing user notification preferences
- Internal creation & bulk updates

Endpoint Path Prefix
---------------------
/api/method/recruitrain_employer.api.notifications.<function_name>
"""

from __future__ import annotations

import json
from typing import Any

import frappe

from recruitrain_employer.services.notification_service import NotificationService
from recruitrain_employer.utils.exceptions import ATSException, ATSValidationError
from recruitrain_employer.utils.permissions import (
    employer_required,
    get_current_company,
    get_current_employer_user,
)
from recruitrain_employer.utils.response import (
    error_response,
    paginated_response,
    success_response,
)
from recruitrain_employer.validators.notification_validator import NotificationValidator


def _handle_ats_exception(exc: Exception) -> dict[str, Any]:
    """Translate an ATSException or general Exception into a standardised error response dict."""
    if isinstance(exc, ATSException):
        return error_response(
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )
    return error_response(
        code="INTERNAL_SERVER_ERROR",
        message=str(exc),
        http_status_code=500,
    )


def _get_request_data() -> dict[str, Any]:
    """Extract form dict data and JSON payload safely from current request."""
    data = dict(frappe.form_dict or {})

    if hasattr(frappe, "request") and frappe.request:
        try:
            json_payload = frappe.request.get_json()
            if isinstance(json_payload, dict):
                data.update(json_payload)
        except Exception:
            pass

    return data


# ---------------------------------------------------------------------------
# Notification Retrieval & Counts
# ---------------------------------------------------------------------------


@frappe.whitelist()
@employer_required
def list_notifications() -> dict[str, Any]:
    """Return a paginated list of notifications for the authenticated user."""
    try:
        user_info = get_current_employer_user()
        user = user_info["user"]
        company = get_current_company()

        req_data = _get_request_data()
        options = NotificationValidator.validate_list_params(req_data)

        service = NotificationService()
        result = service.list_notifications(user=user, company=company, options=options)

        return paginated_response(
            data=result["data"],
            page=result["page"],
            page_size=result["page_size"],
            total=result["total"],
        )
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_notifications() -> dict[str, Any]:
    """Alias for list_notifications."""
    return list_notifications()


@frappe.whitelist()
@employer_required
def get_notification(notification_id: str | None = None) -> dict[str, Any]:
    """Retrieve a single notification record by ID."""
    try:
        req_data = _get_request_data()
        target_id = (
            notification_id
            or req_data.get("notification_id")
            or req_data.get("id")
            or req_data.get("name")
        )

        user_info = get_current_employer_user()
        user = user_info["user"]
        company = get_current_company()

        service = NotificationService()
        record = service.get_notification(notification_id=target_id, user=user, company=company)

        return success_response(data=record)
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def notification_counts() -> dict[str, Any]:
    """Return total count, unread count, and priority counts for notifications."""
    try:
        user_info = get_current_employer_user()
        user = user_info["user"]
        company = get_current_company()

        service = NotificationService()
        counts = service.get_notification_counts(user=user, company=company)

        return success_response(data=counts)
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_unread_count() -> dict[str, Any]:
    """Alias returning unread notification count indicator."""
    try:
        user_info = get_current_employer_user()
        user = user_info["user"]
        company = get_current_company()

        service = NotificationService()
        count = service.get_unread_count(user=user, company=company)

        return success_response(data={"unread_count": count})
    except Exception as exc:
        return _handle_ats_exception(exc)


# ---------------------------------------------------------------------------
# Notification Actions
# ---------------------------------------------------------------------------


@frappe.whitelist()
@employer_required
def mark_notification_read(notification_id: str | None = None) -> dict[str, Any]:
    """Mark a single notification as read."""
    try:
        req_data = _get_request_data()
        target_id = (
            notification_id
            or req_data.get("notification_id")
            or req_data.get("id")
            or req_data.get("name")
        )

        user_info = get_current_employer_user()
        user = user_info["user"]
        company = get_current_company()

        service = NotificationService()
        record = service.mark_notification_read(notification_id=target_id, user=user, company=company)

        return success_response(data=record, message="Notification marked as read.")
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def mark_as_read(notification_id: str | None = None) -> dict[str, Any]:
    """Alias for mark_notification_read."""
    return mark_notification_read(notification_id=notification_id)


@frappe.whitelist()
@employer_required
def mark_all_notifications_read() -> dict[str, Any]:
    """Mark all unread notifications for the user as read."""
    try:
        user_info = get_current_employer_user()
        user = user_info["user"]
        company = get_current_company()

        service = NotificationService()
        count = service.mark_all_notifications_read(user=user, company=company)

        return success_response(
            data={"marked_count": count},
            message=f"{count} notification(s) marked as read.",
        )
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def mark_all_as_read() -> dict[str, Any]:
    """Alias for mark_all_notifications_read."""
    return mark_all_notifications_read()


@frappe.whitelist()
@employer_required
def delete_notification(notification_id: str | None = None) -> dict[str, Any]:
    """Delete a single notification record."""
    try:
        req_data = _get_request_data()
        target_id = (
            notification_id
            or req_data.get("notification_id")
            or req_data.get("id")
            or req_data.get("name")
        )

        user_info = get_current_employer_user()
        user = user_info["user"]
        company = get_current_company()

        service = NotificationService()
        service.delete_notification(notification_id=target_id, user=user, company=company)

        return success_response(message=f"Notification '{target_id}' deleted successfully.")
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def clear_notifications() -> dict[str, Any]:
    """Clear all (or read-only) notifications for the authenticated user."""
    try:
        req_data = _get_request_data()
        read_only_raw = req_data.get("read_only")
        read_only = str(read_only_raw).lower() in ("true", "1", "yes") if read_only_raw else False

        user_info = get_current_employer_user()
        user = user_info["user"]
        company = get_current_company()

        service = NotificationService()
        count = service.clear_notifications(user=user, company=company, read_only=read_only)

        return success_response(
            data={"cleared_count": count},
            message=f"Cleared {count} notification(s).",
        )
    except Exception as exc:
        return _handle_ats_exception(exc)


# ---------------------------------------------------------------------------
# Notification Preferences
# ---------------------------------------------------------------------------


@frappe.whitelist()
@employer_required
def notification_preferences() -> dict[str, Any]:
    """Return the current user's notification preference flags."""
    try:
        user_info = get_current_employer_user()
        user = user_info["user"]
        company = get_current_company()

        service = NotificationService()
        prefs = service.get_notification_preferences(user=user, company=company)

        return success_response(data=prefs)
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_notification_preferences() -> dict[str, Any]:
    """Alias for notification_preferences."""
    return notification_preferences()


@frappe.whitelist()
@employer_required
def update_notification_preferences() -> dict[str, Any]:
    """Update the current user's notification preferences."""
    try:
        user_info = get_current_employer_user()
        user = user_info["user"]
        company = get_current_company()

        req_data = _get_request_data()
        preferences_input = req_data.get("preferences") or req_data

        # Filter out internal frappe keys if preferences was passed as flat dict
        if isinstance(preferences_input, dict):
            preferences_input = {
                k: v
                for k, v in preferences_input.items()
                if k not in ("cmd", "csrf_token", "doctype", "docname")
            }

        service = NotificationService()
        updated = service.update_notification_preferences(
            user=user,
            company=company,
            raw_preferences=preferences_input,
        )

        return success_response(data=updated, message="Notification preferences updated successfully.")
    except Exception as exc:
        return _handle_ats_exception(exc)


# ---------------------------------------------------------------------------
# Advanced / Optional Operations
# ---------------------------------------------------------------------------


@frappe.whitelist()
@employer_required
def create_notification() -> dict[str, Any]:
    """Create a new notification (for internal API or admin trigger)."""
    try:
        user_info = get_current_employer_user()
        sender_user = user_info["user"]
        company = get_current_company()

        req_data = _get_request_data()
        recipient = req_data.get("recipient") or sender_user

        service = NotificationService()
        created = service.create_notification(
            raw_data=req_data,
            company=company,
            recipient=recipient,
            created_by=sender_user,
        )

        return success_response(data=created, message="Notification created successfully.")
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def bulk_update_notifications() -> dict[str, Any]:
    """Perform bulk updates (e.g. mark multiple notifications as read or delete)."""
    try:
        user_info = get_current_employer_user()
        user = user_info["user"]
        company = get_current_company()

        req_data = _get_request_data()
        notification_ids = req_data.get("notification_ids") or req_data.get("ids") or []
        action = str(req_data.get("action") or "").lower()

        if not isinstance(notification_ids, list) or not notification_ids:
            raise ATSValidationError("Field 'notification_ids' must be a non-empty array of notification IDs.")

        if action not in ("read", "mark_read", "delete"):
            raise ATSValidationError("Field 'action' must be 'read' or 'delete'.")

        service = NotificationService()
        processed_count = 0

        for notif_id in notification_ids:
            try:
                if action in ("read", "mark_read"):
                    service.mark_notification_read(str(notif_id), user, company)
                elif action == "delete":
                    service.delete_notification(str(notif_id), user, company)
                processed_count += 1
            except ATSException:
                pass  # Skip records user doesn't own

        return success_response(
            data={"processed_count": processed_count},
            message=f"Bulk action '{action}' performed on {processed_count} notifications.",
        )
    except Exception as exc:
        return _handle_ats_exception(exc)
