# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.services.notification_service
====================================================

Notification Business Logic Service.

Owns all business logic for user in-app notifications targeting Frappe's
installed ``Notification Log`` DocType and custom fields.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe.utils import now_datetime

from recruitrain_employer.utils.constants import (
    DEFAULT_NOTIFICATION_PREFERENCES,
    DOCTYPE_EMPLOYER_USER,
    DOCTYPE_NOTIFICATION,
)
from recruitrain_employer.utils.exceptions import (
    ATSNotFoundError,
    ATSPermissionError,
    ATSServiceError,
)
from recruitrain_employer.validators.notification_validator import NotificationValidator


class NotificationService:
    """Encapsulates business logic for notification management."""

    # ------------------------------------------------------------------
    # Notification Retrieval & Counts
    # ------------------------------------------------------------------

    def list_notifications(
        self,
        user: str,
        company: str,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        """Return a paginated list of notifications for user and company."""
        page = options.get("page", 1)
        page_size = options.get("page_size", 20)
        unread_only = options.get("unread_only")
        priority = options.get("priority")
        notification_type = options.get("notification_type")
        category = options.get("category")
        search = options.get("search", "")
        order_by = options.get("order_by", "creation")
        order_dir = options.get("order_dir", "desc")
        from_date = options.get("from_date")
        to_date = options.get("to_date")

        # Map order_by field if using API contract names
        order_by_map = {
            "title": "subject",
            "message": "email_content",
            "notification_type": "type",
            "is_read": "read",
            "created_on": "creation",
        }
        actual_order_by = order_by_map.get(order_by, order_by)

        filters: dict[str, Any] = {
            "for_user": user,
        }

        # Dynamically check meta for company field availability
        meta = frappe.get_meta(DOCTYPE_NOTIFICATION)
        has_company_field = meta.has_field("company")
        if has_company_field and company:
            filters["company"] = company

        if unread_only is True:
            filters["read"] = 0
        elif unread_only is False:
            filters["read"] = 1

        if priority and meta.has_field("priority"):
            filters["priority"] = priority

        if notification_type:
            filters["type"] = notification_type

        if category and meta.has_field("category"):
            filters["category"] = category

        if from_date and to_date:
            filters["creation"] = ["between", [from_date, to_date]]
        elif from_date:
            filters["creation"] = [">=", from_date]
        elif to_date:
            filters["creation"] = ["<=", to_date]

        or_filters = None
        if search:
            or_filters = [
                ["subject", "like", f"%{search}%"],
                ["email_content", "like", f"%{search}%"],
                ["document_name", "like", f"%{search}%"],
            ]

        order_by_clause = f"{actual_order_by} {order_dir}"

        fields = [
            "name",
            "subject",
            "email_content",
            "type",
            "read",
            "document_type",
            "document_name",
            "from_user",
            "link",
            "email_header",
            "creation",
        ]
        for optional_field in ("company", "priority", "category", "recipient_type", "read_at", "metadata"):
            if meta.has_field(optional_field):
                fields.append(optional_field)

        try:
            records = frappe.get_all(
                DOCTYPE_NOTIFICATION,
                filters=filters,
                or_filters=or_filters,
                fields=fields,
                order_by=order_by_clause,
                start=(page - 1) * page_size,
                page_length=page_size,
            )

            if or_filters:
                total = len(
                    frappe.get_all(
                        DOCTYPE_NOTIFICATION,
                        filters=filters,
                        or_filters=or_filters,
                        pluck="name",
                        ignore_permissions=True,
                    )
                )
            else:
                total = frappe.db.count(DOCTYPE_NOTIFICATION, filters=filters)

            unread_filter = {"for_user": user, "read": 0}
            if has_company_field and company:
                unread_filter["company"] = company
            unread_count = frappe.db.count(DOCTYPE_NOTIFICATION, filters=unread_filter)

            formatted_data = [self._serialize_notification(r) for r in records]

            return {
                "data": formatted_data,
                "total": total,
                "unread_count": unread_count,
                "page": page,
                "page_size": page_size,
            }
        except Exception as exc:
            raise ATSServiceError(
                f"Failed to retrieve notifications: {str(exc)}",
                details={"user": user, "company": company},
            )

    def get_notification(
        self,
        notification_id: str,
        user: str,
        company: str,
    ) -> dict[str, Any]:
        """Retrieve a single notification by ID with security checks."""
        if not notification_id:
            raise ATSNotFoundError("Notification ID must be provided.", doctype=DOCTYPE_NOTIFICATION, name="")

        if not frappe.db.exists(DOCTYPE_NOTIFICATION, notification_id):
            raise ATSNotFoundError(
                f"Notification '{notification_id}' not found.",
                doctype=DOCTYPE_NOTIFICATION,
                name=notification_id,
            )

        meta = frappe.get_meta(DOCTYPE_NOTIFICATION)
        fields = [
            "name",
            "subject",
            "for_user",
            "email_content",
            "type",
            "read",
            "document_type",
            "document_name",
            "from_user",
            "link",
            "email_header",
            "creation",
        ]
        for optional_field in ("company", "priority", "category", "recipient_type", "read_at", "metadata"):
            if meta.has_field(optional_field):
                fields.append(optional_field)

        record = frappe.get_value(
            DOCTYPE_NOTIFICATION,
            notification_id,
            fields,
            as_dict=True,
        )

        if not record:
            raise ATSNotFoundError(
                f"Notification '{notification_id}' not found.",
                doctype=DOCTYPE_NOTIFICATION,
                name=notification_id,
            )

        if record.get("for_user") != user:
            raise ATSPermissionError("You do not have access to this notification.")

        if meta.has_field("company") and record.get("company") and record.get("company") != company:
            raise ATSPermissionError("You do not have access to this notification.")

        return self._serialize_notification(record)

    def get_unread_count(self, user: str, company: str) -> int:
        """Return count of unread notifications for user."""
        filters = {"for_user": user, "read": 0}
        meta = frappe.get_meta(DOCTYPE_NOTIFICATION)
        if meta.has_field("company") and company:
            filters["company"] = company

        return frappe.db.count(DOCTYPE_NOTIFICATION, filters=filters)

    def get_notification_counts(self, user: str, company: str) -> dict[str, int]:
        """Return statistics for user's notifications."""
        meta = frappe.get_meta(DOCTYPE_NOTIFICATION)
        filters = {"for_user": user}
        if meta.has_field("company") and company:
            filters["company"] = company

        total = frappe.db.count(DOCTYPE_NOTIFICATION, filters=filters)

        unread_filters = dict(filters)
        unread_filters["read"] = 0
        unread = frappe.db.count(DOCTYPE_NOTIFICATION, filters=unread_filters)

        read = total - unread

        high_priority_unread = 0
        urgent_unread = 0
        if meta.has_field("priority"):
            high_filters = dict(unread_filters)
            high_filters["priority"] = "High"
            high_priority_unread = frappe.db.count(DOCTYPE_NOTIFICATION, filters=high_filters)

            urgent_filters = dict(unread_filters)
            urgent_filters["priority"] = "Urgent"
            urgent_unread = frappe.db.count(DOCTYPE_NOTIFICATION, filters=urgent_filters)

        return {
            "unread": unread,
            "read": read,
            "total": total,
            "high_priority_unread": high_priority_unread,
            "urgent_unread": urgent_unread,
        }

    # ------------------------------------------------------------------
    # Notification Actions
    # ------------------------------------------------------------------

    def mark_notification_read(
        self,
        notification_id: str,
        user: str,
        company: str,
    ) -> dict[str, Any]:
        """Mark a single notification as read."""
        record = self.get_notification(notification_id, user, company)

        if record.get("is_read"):
            return record

        now_time = now_datetime()
        meta = frappe.get_meta(DOCTYPE_NOTIFICATION)

        update_values = {"read": 1}
        if meta.has_field("read_at"):
            update_values["read_at"] = now_time

        frappe.db.set_value(
            DOCTYPE_NOTIFICATION,
            notification_id,
            update_values,
            update_modified=False,
        )

        record["is_read"] = True
        record["read_at"] = str(now_time)
        return record

    def mark_all_notifications_read(self, user: str, company: str) -> int:
        """Mark all unread notifications for user as read."""
        meta = frappe.get_meta(DOCTYPE_NOTIFICATION)
        filters = {"for_user": user, "read": 0}
        if meta.has_field("company") and company:
            filters["company"] = company

        unread_records = frappe.get_all(
            DOCTYPE_NOTIFICATION,
            filters=filters,
            fields=["name"],
        )

        if not unread_records:
            return 0

        now_time = now_datetime()
        update_values = {"read": 1}
        if meta.has_field("read_at"):
            update_values["read_at"] = now_time

        for rec in unread_records:
            frappe.db.set_value(
                DOCTYPE_NOTIFICATION,
                rec["name"],
                update_values,
                update_modified=False,
            )

        return len(unread_records)

    def delete_notification(
        self,
        notification_id: str,
        user: str,
        company: str,
    ) -> None:
        """Delete a notification record after verification."""
        self.get_notification(notification_id, user, company)
        frappe.delete_doc(
            DOCTYPE_NOTIFICATION,
            notification_id,
            ignore_permissions=True,
        )

    def clear_notifications(
        self,
        user: str,
        company: str,
        read_only: bool = False,
    ) -> int:
        """Clear notifications for current user."""
        meta = frappe.get_meta(DOCTYPE_NOTIFICATION)
        filters = {"for_user": user}
        if meta.has_field("company") and company:
            filters["company"] = company

        if read_only:
            filters["read"] = 1

        records = frappe.get_all(
            DOCTYPE_NOTIFICATION,
            filters=filters,
            fields=["name"],
        )

        count = 0
        for rec in records:
            frappe.delete_doc(
                DOCTYPE_NOTIFICATION,
                rec["name"],
                ignore_permissions=True,
            )
            count += 1

        return count

    # ------------------------------------------------------------------
    # Notification Preferences
    # ------------------------------------------------------------------

    def get_notification_preferences(self, user: str, company: str) -> dict[str, bool]:
        """Fetch user notification preferences."""
        emp_user_meta = frappe.get_meta(DOCTYPE_EMPLOYER_USER)
        if not emp_user_meta.has_field("notification_preferences"):
            return dict(DEFAULT_NOTIFICATION_PREFERENCES)

        emp_user = frappe.db.get_value(
            DOCTYPE_EMPLOYER_USER,
            {"user": user},
            ["name", "notification_preferences"],
            as_dict=True,
        )

        if not emp_user:
            return dict(DEFAULT_NOTIFICATION_PREFERENCES)

        prefs_str = emp_user.get("notification_preferences")
        if not prefs_str:
            return dict(DEFAULT_NOTIFICATION_PREFERENCES)

        try:
            stored_prefs = json.loads(prefs_str)
            if isinstance(stored_prefs, dict):
                result = dict(DEFAULT_NOTIFICATION_PREFERENCES)
                result.update(stored_prefs)
                return result
        except json.JSONDecodeError:
            frappe.logger().warning(
                f"Invalid JSON in notification_preferences for user '{user}'. Falling back to defaults."
            )

        return dict(DEFAULT_NOTIFICATION_PREFERENCES)

    def update_notification_preferences(
        self,
        user: str,
        company: str,
        raw_preferences: dict[str, Any],
    ) -> dict[str, bool]:
        """Update notification preferences on Employer User record."""
        validated_prefs = NotificationValidator.validate_preferences(raw_preferences)

        emp_user_name = frappe.db.get_value(
            DOCTYPE_EMPLOYER_USER,
            {"user": user},
            "name",
        )

        if not emp_user_name:
            raise ATSNotFoundError(f"Employer User record not found for '{user}'.")

        current_prefs = self.get_notification_preferences(user, company)
        current_prefs.update(validated_prefs)

        emp_user_meta = frappe.get_meta(DOCTYPE_EMPLOYER_USER)
        if emp_user_meta.has_field("notification_preferences"):
            frappe.db.set_value(
                DOCTYPE_EMPLOYER_USER,
                emp_user_name,
                "notification_preferences",
                json.dumps(current_prefs),
            )

        return current_prefs

    # ------------------------------------------------------------------
    # Notification Creation
    # ------------------------------------------------------------------

    def create_notification(
        self,
        raw_data: dict[str, Any],
        company: str,
        recipient: str,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        """Create a new Notification Log document."""
        data = NotificationValidator.validate_create(raw_data)
        meta = frappe.get_meta(DOCTYPE_NOTIFICATION)

        sender = created_by or getattr(frappe.session, "user", None)
        if not sender or not frappe.db.exists("User", sender):
            sender = getattr(frappe.session, "user", "Administrator")
            if not frappe.db.exists("User", sender):
                sender = "Administrator"

        doc_dict = {
            "doctype": DOCTYPE_NOTIFICATION,
            "subject": data["title"],
            "email_content": data["message"],
            "for_user": recipient,
            "type": data["notification_type"],
            "read": 0,
            "from_user": sender,
            "document_type": data.get("entity_type") or "Notification Log",
            "document_name": data.get("entity_id") or "",
            "link": data.get("action_url") or "",
            "email_header": data.get("action_label") or data.get("title") or "New Notification",
        }

        if meta.has_field("company"):
            doc_dict["company"] = company
        if meta.has_field("priority"):
            doc_dict["priority"] = data["priority"]
        if meta.has_field("category"):
            doc_dict["category"] = data["category"]
        if meta.has_field("recipient_type"):
            doc_dict["recipient_type"] = raw_data.get("recipient_type", "Employer User")
        if meta.has_field("metadata"):
            doc_dict["metadata"] = data.get("metadata")

        try:
            doc = frappe.get_doc(doc_dict)
            doc.insert(ignore_permissions=True)
            return self._serialize_notification(doc.as_dict())
        except Exception as exc:
            raise ATSServiceError(
                f"Failed to create notification: {str(exc)}",
                details={"title": data["title"], "recipient": recipient},
            )

    # ------------------------------------------------------------------
    # Serialization Helper
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_notification(record: dict[str, Any]) -> dict[str, Any]:
        """Normalize Notification Log record into standardized API contract format."""
        metadata_val = record.get("metadata")
        metadata_dict = None
        if metadata_val:
            if isinstance(metadata_val, dict):
                metadata_dict = metadata_val
            elif isinstance(metadata_val, str):
                try:
                    metadata_dict = json.loads(metadata_val)
                except json.JSONDecodeError:
                    metadata_dict = None

        return {
            "name": str(record.get("name") or ""),
            "title": str(record.get("subject") or ""),
            "message": str(record.get("email_content") or ""),
            "notification_type": str(record.get("type") or "General"),
            "priority": str(record.get("priority") or "Medium"),
            "category": str(record.get("category") or "General"),
            "company": str(record.get("company") or ""),
            "recipient": str(record.get("for_user") or ""),
            "recipient_type": str(record.get("recipient_type") or "Employer User"),
            "is_read": bool(record.get("read")),
            "read_at": str(record.get("read_at")) if record.get("read_at") else None,
            "created_by": str(record.get("from_user") or ""),
            "action_url": str(record.get("link")) if record.get("link") else None,
            "action_label": str(record.get("email_header")) if record.get("email_header") else None,
            "entity_type": str(record.get("document_type")) if record.get("document_type") else None,
            "entity_id": str(record.get("document_name")) if record.get("document_name") else None,
            "metadata": metadata_dict,
            "created_on": str(record.get("creation") or ""),
        }
