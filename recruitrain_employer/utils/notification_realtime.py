# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.utils.notification_realtime
=================================================

Central publisher for RecruitTrain realtime notifications using Frappe Socket.IO infrastructure.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import cstr, get_datetime


def publish_notification_realtime(notification_record: dict[str, Any] | Any) -> bool:
    """Publish a realtime notification event via Frappe Socket.IO targeted strictly to the recipient.

    Parameters
    ----------
    notification_record : dict or Document
        Authoritative Notification Log database record.

    Returns
    -------
    bool
        True if successfully queued/published, False otherwise.
    """
    if not notification_record:
        return False

    if hasattr(notification_record, "as_dict") and callable(getattr(notification_record, "as_dict", None)):
        record = notification_record.as_dict()
    elif isinstance(notification_record, dict):
        record = notification_record
    else:
        return False

    # Extract recipient user strictly from server database record
    recipient = record.get("recipient") or record.get("for_user")
    if not recipient or recipient == "Guest":
        return False

    company = record.get("company")
    notif_id = cstr(record.get("name") or record.get("id"))
    title = cstr(record.get("title") or record.get("subject") or "Notification")
    message = cstr(record.get("message") or record.get("email_content") or "")
    notif_type = cstr(record.get("notification_type") or record.get("type") or "System")
    priority = cstr(record.get("priority") or "Medium")
    category = cstr(record.get("category") or "recruitment")
    action_url = cstr(record.get("action_url") or record.get("link") or "")
    action_label = cstr(record.get("action_label") or record.get("email_header") or title)
    entity_type = cstr(record.get("entity_type") or record.get("document_type") or "")
    entity_id = cstr(record.get("entity_id") or record.get("document_name") or "")

    created_at_raw = record.get("creation") or record.get("created_at")
    created_at = get_datetime(created_at_raw).isoformat() if created_at_raw else frappe.utils.now()

    payload = {
        "notification_id": notif_id,
        "id": notif_id,
        "title": title,
        "message": message,
        "type": notif_type,
        "notification_type": notif_type,
        "priority": priority,
        "category": category,
        "action_url": action_url,
        "action_label": action_label,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "created_at": created_at,
        "creation": created_at,
        "company": company,
        "is_read": False,
        "read": False,
    }

    try:
        frappe.publish_realtime(
            event="recruittrain_notification",
            message=payload,
            user=recipient,
            after_commit=True,
        )
        return True
    except Exception as exc:
        frappe.logger("notification_realtime").error(
            f"Failed to publish realtime notification '{notif_id}' to user '{recipient}': {str(exc)}"
        )
        return False
