# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.services.push_service
==========================================

Central Web Push Notification Dispatch Service.

Responsibilities:
- Encapsulate standards-based Web Push payload formatting and VAPID signing.
- Query active subscriptions belonging strictly to target user and company.
- Respect user notification preferences (browser_push_notifications channel).
- Deactivate expired/invalid browser endpoints upon Web Push provider errors.
- Sanitize payload contents to eliminate sensitive internal credentials or session data.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from pywebpush import WebPushException, webpush

from recruitrain_employer.utils.vapid_config import get_vapid_credentials


class PushService:
    """Service handling Web Push notification delivery."""

    @staticmethod
    def sanitize_action_url(action_url: str | None) -> str:
        """Sanitize action URL to ensure only application-relative paths are used."""
        if not action_url or not isinstance(action_url, str):
            return "/app/notifications"
        trimmed = action_url.strip()
        if trimmed.startswith("http://") or trimmed.startswith("https://") or trimmed.startswith("//"):
            # Disallow external URL injection
            return "/app/notifications"
        if not trimmed.startswith("/"):
            return f"/{trimmed}"
        return trimmed

    def send_notification_push(self, notification_record: dict[str, Any] | Any) -> int:
        """Send Web Push notification to all active browser subscriptions of recipient.

        Parameters
        ----------
        notification_record : dict | Document
            Notification Log record containing recipient, company, title, message, etc.

        Returns
        -------
        int
            Count of successfully dispatched push notifications.
        """
        if not notification_record:
            return 0

        # Convert Document to dict if needed
        if hasattr(notification_record, "as_dict") and callable(getattr(notification_record, "as_dict", None)):
            record = notification_record.as_dict()
        elif isinstance(notification_record, dict):
            record = notification_record
        else:
            return 0

        recipient = record.get("recipient")
        company = record.get("company")

        if not recipient or recipient == "Guest" or not company:
            return 0

        # Check user notification preferences for browser_push_notifications
        from recruitrain_employer.services.notification_service import NotificationService
        notif_service = NotificationService()
        user_prefs = notif_service.get_notification_preferences(recipient, company)

        if not bool(user_prefs.get("browser_push_notifications", True)):
            frappe.logger().debug(f"Web push suppressed for user '{recipient}' via preferences.")
            return 0

        # Also respect specific category preference (e.g. interview, job, offer, etc.)
        category = (record.get("category") or record.get("notification_type") or "").lower()
        if category in user_prefs and not bool(user_prefs[category]):
            frappe.logger().debug(f"Web push suppressed for category '{category}' for user '{recipient}'.")
            return 0

        # Query active subscriptions for recipient & company
        subscriptions = frappe.get_all(
            "RecruitTrain Push Subscription",
            filters={
                "user": recipient,
                "company": company,
                "is_active": 1,
            },
            fields=["name", "endpoint", "p256dh", "auth"],
        )

        frappe.logger().info(
            f"[PushService] Found {len(subscriptions)} active subscription(s) for user '{recipient}' in company '{company}'."
        )

        if not subscriptions:
            return 0

        pub_key, priv_key_pem, subject = get_vapid_credentials()
        from py_vapid import Vapid
        vapid_obj = Vapid.from_pem(priv_key_pem.encode("utf-8")) if isinstance(priv_key_pem, str) else priv_key_pem

        notif_id = str(record.get("name") or record.get("id") or "")
        title = str(record.get("title") or "RecruiTrain Alert")
        body = str(record.get("message") or "")
        action_url = self.sanitize_action_url(record.get("action_url"))

        # Payload structure for Web Push Service Worker
        payload = {
            "notification_id": notif_id,
            "id": notif_id,
            "title": title,
            "body": body,
            "message": body,
            "icon": "/logo.png",
            "badge": "/badge.png",
            "action_url": action_url,
            "entity_type": str(record.get("entity_type") or ""),
            "entity_id": str(record.get("entity_id") or ""),
            "priority": str(record.get("priority") or "Medium"),
            "category": str(record.get("category") or "general"),
        }

        # Sanitize payload: strip any internal sensitive keys
        forbidden_keys = {"password", "sid", "token", "secret", "cookie", "authorization", "session"}
        for k in list(payload.keys()):
            if k.lower() in forbidden_keys:
                payload.pop(k, None)

        sent_count = 0

        for sub in subscriptions:
            sub_info = {
                "endpoint": sub["endpoint"],
                "keys": {
                    "p256dh": sub["p256dh"],
                    "auth": sub["auth"],
                },
            }

            try:
                frappe.logger().info(
                    f"NOTIF DEBUG: ID = {notif_id} SERVICE = push SENDing to endpoint '{sub['endpoint'][:30]}...'"
                )
                res = webpush(
                    subscription_info=sub_info,
                    data=json.dumps(payload),
                    vapid_private_key=vapid_obj,
                    vapid_claims={"sub": subject},
                    ttl=86400,
                )
                sent_count += 1
                status_code = getattr(res, "status_code", 201) if res else 201
                frappe.logger().info(
                    f"NOTIF DEBUG: ID = {notif_id} SERVICE = push SEND = SUCCESS (HTTP {status_code})"
                )
                frappe.db.set_value(
                    "RecruitTrain Push Subscription",
                    sub["name"],
                    "last_used_at",
                    frappe.utils.now(),
                    update_modified=False,
                )
            except WebPushException as ex:
                status_code = getattr(ex.response, "status_code", None) if hasattr(ex, "response") else None
                resp_body = getattr(ex.response, "text", str(ex)) if hasattr(ex, "response") else str(ex)
                sanitized_reason = str(resp_body)[:500].replace("\r", " ").replace("\n", " ")
                from urllib.parse import urlparse
                endpoint_host = urlparse(sub.get("endpoint", "")).netloc or "unknown"
                frappe.logger("web_push").error(
                    f"[RT-PUSH-ERROR]\n"
                    f"status={status_code}\n"
                    f"endpoint_host={endpoint_host}\n"
                    f"reason={sanitized_reason}\n"
                    f"exception_type={type(ex).__name__}\n"
                    f"subscription_id={sub.get('name')}"
                )
                # If subscription has expired / 404 / 410 Gone / 400 invalid:
                if status_code in (400, 401, 403, 404, 410):
                    frappe.db.set_value(
                        "RecruitTrain Push Subscription",
                        sub["name"],
                        "is_active",
                        0,
                        update_modified=False,
                    )
                    frappe.logger().info(f"[PushService] Deactivated invalid subscription '{sub['name']}' (HTTP {status_code}).")
            except Exception as ex:
                frappe.logger("web_push").error(f"[PushService] Unexpected Web Push error for '{sub['name']}': {type(ex).__name__} - {ex}")

        return sent_count


def send_notification_push(notification_record: dict[str, Any] | Any) -> int:
    """Module-level entry point to dispatch web push notifications."""
    service = PushService()
    return service.send_notification_push(notification_record)
