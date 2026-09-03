# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api.push
=============================

API Controller for Web Push Subscriptions and Public Key Distribution.

Endpoints:
- get_vapid_public_key: Returns the public VAPID key for browser subscription.
- subscribe_push: Registers or updates a browser PushSubscription.
- unsubscribe_push: Unsubscribes a browser endpoint.
- get_push_subscriptions: Lists subscriptions for the current employer user.
- delete_push_subscription: Permanently deletes a subscription record.

All endpoints strictly enforce:
- Authenticated Employer User session.
- Tenant & Company isolation.
- Zero client-supplied recipient or company spoofing.
"""

from __future__ import annotations

import json
from typing import Any

import frappe

from recruitrain_employer.utils.exceptions import (
    ATSNotFoundError,
    ATSPermissionError,
    ATSValidationError,
)
from recruitrain_employer.utils.permissions import employer_required, get_current_company, get_current_employer_user
from recruitrain_employer.utils.response import error_response, success_response
from recruitrain_employer.utils.vapid_config import get_vapid_public_key_string


def _get_request_data() -> dict[str, Any]:
    """Helper to extract request JSON data or form dict."""
    data = {}
    if frappe.request and getattr(frappe.request, "data", None):
        try:
            raw = frappe.request.data
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            if raw:
                data = json.loads(raw)
        except Exception:
            data = {}

    if not data and hasattr(frappe, "form_dict"):
        data = dict(frappe.form_dict or {})

    return data


@frappe.whitelist()
@employer_required
def get_vapid_public_key() -> dict[str, Any]:
    """Return public VAPID key for Web Push subscription."""
    try:
        pub_key = get_vapid_public_key_string()
        return success_response(data={"public_key": pub_key})
    except Exception as exc:
        frappe.logger().error(f"Error fetching VAPID public key: {exc}")
        return error_response(code="SERVER_ERROR", message=str(exc), http_status_code=500)


@frappe.whitelist()
@employer_required
def subscribe_push() -> dict[str, Any]:
    """Register or update a browser Web Push subscription."""
    try:
        user_info = get_current_employer_user()
        user = user_info["user"]
        company = get_current_company()

        data = _get_request_data()

        endpoint = data.get("endpoint")
        keys = data.get("keys") or {}
        p256dh = keys.get("p256dh") or data.get("p256dh")
        auth = keys.get("auth") or data.get("auth")
        expiration_time = data.get("expirationTime") or data.get("expiration_time")

        device_name = data.get("device_name") or data.get("user_agent")
        user_agent = data.get("user_agent") or (frappe.request.headers.get("User-Agent") if frappe.request else "")
        platform = data.get("platform")
        browser = data.get("browser")

        if not endpoint or not isinstance(endpoint, str):
            raise ATSValidationError("Subscription endpoint is required.", field="endpoint")
        if not p256dh or not isinstance(p256dh, str):
            raise ATSValidationError("P256DH key is required.", field="p256dh")
        if not auth or not isinstance(auth, str):
            raise ATSValidationError("Auth secret is required.", field="auth")

        endpoint = endpoint.strip()
        p256dh = p256dh.strip()
        auth = auth.strip()

        # Check if subscription endpoint already exists
        existing_sub = frappe.db.get_value(
            "RecruitTrain Push Subscription",
            {"endpoint": endpoint},
            ["name", "user", "company"],
            as_dict=True,
        )

        if existing_sub:
            sub_doc = frappe.get_doc("RecruitTrain Push Subscription", existing_sub["name"])
            sub_doc.user = user
            sub_doc.company = company
            sub_doc.p256dh = p256dh
            sub_doc.auth = auth
            sub_doc.expiration_time = expiration_time
            sub_doc.device_name = device_name
            sub_doc.user_agent = user_agent
            sub_doc.platform = platform
            sub_doc.browser = browser
            sub_doc.is_active = 1
            sub_doc.last_used_at = frappe.utils.now()
            sub_doc.save(ignore_permissions=True)
            frappe.db.commit()
            action = "updated"
        else:
            sub_doc = frappe.get_doc({
                "doctype": "RecruitTrain Push Subscription",
                "user": user,
                "company": company,
                "endpoint": endpoint,
                "p256dh": p256dh,
                "auth": auth,
                "expiration_time": expiration_time,
                "device_name": device_name,
                "user_agent": user_agent,
                "platform": platform,
                "browser": browser,
                "is_active": 1,
                "last_used_at": frappe.utils.now(),
            })
            sub_doc.insert(ignore_permissions=True)
            frappe.db.commit()
            action = "created"

        return success_response(
            data={
                "name": sub_doc.name,
                "endpoint": sub_doc.endpoint,
                "is_active": bool(sub_doc.is_active),
                "action": action,
            },
            message=f"Push subscription successfully {action}.",
        )
    except ATSValidationError as exc:
        return error_response(code="VALIDATION_ERROR", message=exc.message, field=exc.field, http_status_code=400)
    except Exception as exc:
        frappe.logger().error(f"Error subscribing push notification: {exc}")
        return error_response(code="SERVER_ERROR", message=str(exc), http_status_code=500)


@frappe.whitelist()
@employer_required
def unsubscribe_push() -> dict[str, Any]:
    """Unsubscribe a browser Web Push subscription."""
    try:
        user_info = get_current_employer_user()
        user = user_info["user"]
        company = get_current_company()

        data = _get_request_data()
        endpoint = data.get("endpoint") or data.get("subscription_id")

        if not endpoint or not isinstance(endpoint, str):
            raise ATSValidationError("Subscription endpoint is required for unsubscription.", field="endpoint")

        endpoint = endpoint.strip()

        # Find subscription matching endpoint
        sub_list = frappe.get_all(
            "RecruitTrain Push Subscription",
            filters={"endpoint": endpoint},
            fields=["name", "user", "company"],
        )

        if not sub_list:
            raise ATSNotFoundError(f"Push subscription not found for endpoint '{endpoint}'.")

        sub = sub_list[0]

        # Security check: Ensure subscription belongs to current user and company
        if sub["user"] != user or sub["company"] != company:
            raise ATSPermissionError("Access denied. You cannot unsubscribe another user's push subscription.")

        # Deactivate subscription
        sub_doc = frappe.get_doc("RecruitTrain Push Subscription", sub["name"])
        sub_doc.is_active = 0
        sub_doc.save(ignore_permissions=True)
        frappe.db.commit()

        return success_response(
            data={"name": sub_doc.name, "endpoint": endpoint, "is_active": False},
            message="Push subscription unsubscribed successfully.",
        )
    except ATSValidationError as exc:
        return error_response(code="VALIDATION_ERROR", message=exc.message, field=exc.field, http_status_code=400)
    except ATSNotFoundError as exc:
        return error_response(code="NOT_FOUND", message=exc.message, http_status_code=404)
    except ATSPermissionError as exc:
        return error_response(code="PERMISSION_DENIED", message=str(exc), http_status_code=403)
    except Exception as exc:
        frappe.logger().error(f"Error unsubscribing push notification: {exc}")
        return error_response(code="SERVER_ERROR", message=str(exc), http_status_code=500)


@frappe.whitelist()
@employer_required
def get_push_subscriptions() -> dict[str, Any]:
    """List active push subscriptions for the current employer user."""
    try:
        user_info = get_current_employer_user()
        user = user_info["user"]
        company = get_current_company()

        subs = frappe.get_all(
            "RecruitTrain Push Subscription",
            filters={"user": user, "company": company},
            fields=["name", "endpoint", "is_active", "device_name", "browser", "platform", "creation", "last_used_at"],
            order_by="creation desc",
        )

        return success_response(data=subs)
    except Exception as exc:
        return error_response(code="SERVER_ERROR", message=str(exc), http_status_code=500)


@frappe.whitelist()
@employer_required
def delete_push_subscription() -> dict[str, Any]:
    """Delete a push subscription record permanently."""
    try:
        user_info = get_current_employer_user()
        user = user_info["user"]
        company = get_current_company()

        data = _get_request_data()
        name = data.get("name") or data.get("subscription_id") or data.get("endpoint")

        if not name:
            raise ATSValidationError("Subscription name or endpoint is required.", field="name")

        if frappe.db.exists("RecruitTrain Push Subscription", name):
            sub_doc = frappe.get_doc("RecruitTrain Push Subscription", name)
        else:
            sub_list = frappe.get_all("RecruitTrain Push Subscription", filters={"endpoint": name}, fields=["name"])
            if not sub_list:
                raise ATSNotFoundError(f"Push subscription '{name}' not found.")
            sub_doc = frappe.get_doc("RecruitTrain Push Subscription", sub_list[0]["name"])

        # Security check: Ownership & Company isolation
        if sub_doc.user != user or sub_doc.company != company:
            raise ATSPermissionError("Access denied. You cannot delete another user's push subscription.")

        sub_doc.delete(ignore_permissions=True)
        frappe.db.commit()

        return success_response(
            data={"name": sub_doc.name},
            message="Push subscription deleted successfully.",
        )
    except ATSValidationError as exc:
        return error_response(code="VALIDATION_ERROR", message=exc.message, field=exc.field, http_status_code=400)
    except ATSNotFoundError as exc:
        return error_response(code="NOT_FOUND", message=exc.message, http_status_code=404)
    except ATSPermissionError as exc:
        return error_response(code="PERMISSION_DENIED", message=str(exc), http_status_code=403)
    except Exception as exc:
        return error_response(code="SERVER_ERROR", message=str(exc), http_status_code=500)


@frappe.whitelist(methods=["POST"])
@employer_required
def test_web_push() -> dict[str, Any]:
    """
    Development diagnostic endpoint: send a test Web Push to the authenticated user's
    active browser subscriptions.

    Security:
    - Recipient MUST be frappe.session.user (no spoofing).
    - Company MUST be from get_current_company() (no spoofing).
    - Only active subscriptions belonging to this user/company are targeted.
    - No Notification Log record is created.

    Returns
    -------
    dict
        {success, data: {sent, failed, subscriptions}, message}
    """
    import json
    import uuid

    from pywebpush import WebPushException, webpush as _webpush

    from recruitrain_employer.utils.vapid_config import get_vapid_credentials

    try:
        user_info = get_current_employer_user()
        user = user_info["user"]
        company = get_current_company()

        # Query ONLY active subscriptions for this authenticated user/company
        subscriptions = frappe.get_all(
            "RecruitTrain Push Subscription",
            filters={"user": user, "company": company, "is_active": 1},
            fields=["name", "endpoint", "p256dh", "auth"],
        )

        if not subscriptions:
            return error_response(
                code="NO_SUBSCRIPTION",
                message="No active browser push subscription exists for this user. "
                        "Enable browser notifications and reload the page.",
                http_status_code=404,
            )

        pub_key, priv_key_pem, subject = get_vapid_credentials()
        from py_vapid import Vapid
        vapid_obj = Vapid.from_pem(priv_key_pem.encode("utf-8")) if isinstance(priv_key_pem, str) else priv_key_pem

        test_id = f"PUSH-TEST-{uuid.uuid4().hex[:12].upper()}"
        payload = {
            "notification_id": test_id,
            "id": test_id,
            "title": "RecruitTrain Push Test",
            "body": "Browser Web Push is working. This is a direct transport test.",
            "message": "Browser Web Push is working. This is a direct transport test.",
            "action_url": "/app/notifications",
            "type": "System",
            "priority": "Medium",
            "category": "system",
        }

        frappe.logger("web_push").info(
            f"[RT-PUSH] test_web_push: user={user} subscriptions={len(subscriptions)} test_id={test_id}"
        )

        sent = 0
        failed = 0

        for sub in subscriptions:
            sub_info = {
                "endpoint": sub["endpoint"],
                "keys": {
                    "p256dh": sub["p256dh"],
                    "auth": sub["auth"],
                },
            }

            try:
                endpoint_host = sub["endpoint"][:50] if sub["endpoint"] else "?"
                frappe.logger("web_push").info(
                    f"[RT-PUSH] test_web_push: SENDING to endpoint={endpoint_host}..."
                )
                res = _webpush(
                    subscription_info=sub_info,
                    data=json.dumps(payload),
                    vapid_private_key=vapid_obj,
                    vapid_claims={"sub": subject},
                    ttl=86400,
                )
                status_code = getattr(res, "status_code", 201) if res else 201
                frappe.logger("web_push").info(
                    f"[RT-PUSH] test_web_push: SEND_SUCCESS endpoint={endpoint_host}... HTTP={status_code}"
                )
                sent += 1
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
                # Deactivate expired/invalid subscription
                if status_code in (400, 401, 403, 404, 410):
                    frappe.db.set_value(
                        "RecruitTrain Push Subscription",
                        sub["name"],
                        "is_active",
                        0,
                        update_modified=False,
                    )
                    frappe.db.commit()
                failed += 1
            except Exception as ex:
                frappe.logger("web_push").error(
                    f"[RT-PUSH-ERROR]\n"
                    f"status=None\n"
                    f"endpoint_host=unknown\n"
                    f"reason={str(ex)[:500]}\n"
                    f"exception_type={type(ex).__name__}\n"
                    f"subscription_id={sub.get('name')}"
                )
                failed += 1

        if sent == 0 and failed > 0:
            return error_response(
                code="PUSH_FAILED",
                message=f"All {failed} push attempt(s) failed. Check backend logs for HTTP status codes.",
                http_status_code=500,
            )

        return success_response(
            data={
                "sent": sent,
                "failed": failed,
                "subscriptions": len(subscriptions),
                "test_id": test_id,
            },
            message=f"Test push dispatched successfully. Sent: {sent}, Failed: {failed}.",
        )

    except Exception as exc:
        frappe.logger("web_push").error(f"[RT-PUSH] test_web_push error: {exc}")
        return error_response(code="SERVER_ERROR", message=str(exc), http_status_code=500)
