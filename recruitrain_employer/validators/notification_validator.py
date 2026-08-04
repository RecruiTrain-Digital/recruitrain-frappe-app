# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.notification_validator
=========================================================

Input Validation Layer for Notification Operations.

Enforces rules on:
- Notification payload creation
- Query list/filter parameters
- Notification user preferences payloads
"""

from __future__ import annotations

import json
from typing import Any

from recruitrain_employer.utils.constants import (
    ALLOWED_NOTIFICATION_PRIORITIES,
    ALLOWED_NOTIFICATION_TYPES,
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    NOTIFICATION_PRIORITY_MEDIUM,
    NOTIFICATION_TYPE_GENERAL,
)
from recruitrain_employer.utils.exceptions import ATSValidationError


class NotificationValidator:
    """Validator class for notification payloads and query filters."""

    @staticmethod
    def validate_create(data: dict[str, Any]) -> dict[str, Any]:
        """Validate payload for creating a notification.

        Parameters
        ----------
        data : dict
            Input data containing title, message, priority, notification_type, etc.

        Returns
        -------
        dict
            Sanitised and validated notification payload.

        Raises
        ------
        ATSValidationError
            If any field violates schema/type constraints.
        """
        if not isinstance(data, dict):
            raise ATSValidationError("Notification payload must be a JSON object.")

        title = str(data.get("title") or "").strip()
        if not title:
            raise ATSValidationError("Notification title is required.", field="title")
        if len(title) > 255:
            raise ATSValidationError("Notification title cannot exceed 255 characters.", field="title")

        message = str(data.get("message") or "").strip()
        if not message:
            raise ATSValidationError("Notification message is required.", field="message")

        priority = data.get("priority") or NOTIFICATION_PRIORITY_MEDIUM
        if priority not in ALLOWED_NOTIFICATION_PRIORITIES:
            raise ATSValidationError(
                f"Invalid priority '{priority}'. Allowed values: {', '.join(ALLOWED_NOTIFICATION_PRIORITIES)}.",
                field="priority",
            )

        notification_type = data.get("notification_type") or data.get("type") or NOTIFICATION_TYPE_GENERAL
        if notification_type not in ALLOWED_NOTIFICATION_TYPES:
            raise ATSValidationError(
                f"Invalid notification type '{notification_type}'. Allowed values: {', '.join(ALLOWED_NOTIFICATION_TYPES)}.",
                field="notification_type",
            )

        category = str(data.get("category") or notification_type).strip()

        action_url = data.get("action_url")
        if action_url is not None:
            action_url = str(action_url).strip()

        action_label = data.get("action_label")
        if action_label is not None:
            action_label = str(action_label).strip()

        entity_type = data.get("entity_type")
        if entity_type is not None:
            entity_type = str(entity_type).strip()

        entity_id = data.get("entity_id")
        if entity_id is not None:
            entity_id = str(entity_id).strip()

        metadata_raw = data.get("metadata")
        metadata_str = ""
        if metadata_raw:
            if isinstance(metadata_raw, dict):
                metadata_str = json.dumps(metadata_raw)
            elif isinstance(metadata_raw, str):
                try:
                    parsed = json.loads(metadata_raw)
                    if isinstance(parsed, dict):
                        metadata_str = json.dumps(parsed)
                    else:
                        raise ATSValidationError("Metadata JSON string must evaluate to an object.", field="metadata")
                except json.JSONDecodeError:
                    raise ATSValidationError("Metadata must be valid JSON.", field="metadata")
            else:
                raise ATSValidationError("Metadata must be a dict or valid JSON string.", field="metadata")

        return {
            "title": title,
            "message": message,
            "priority": priority,
            "notification_type": notification_type,
            "category": category,
            "action_url": action_url,
            "action_label": action_label,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "metadata": metadata_str,
        }

    @staticmethod
    def validate_list_params(params: dict[str, Any]) -> dict[str, Any]:
        """Validate and parse query string / filter options for notification lists.

        Parameters
        ----------
        params : dict
            Input form dict or query parameters.

        Returns
        -------
        dict
            Sanitised options dictionary with typed page, page_size, filters, etc.
        """
        if not isinstance(params, dict):
            params = {}

        try:
            page = int(params.get("page", DEFAULT_PAGE))
            if page < 1:
                page = DEFAULT_PAGE
        except (ValueError, TypeError):
            page = DEFAULT_PAGE

        try:
            page_size = int(params.get("page_size", DEFAULT_PAGE_SIZE))
            if page_size < 1:
                page_size = DEFAULT_PAGE_SIZE
            elif page_size > MAX_PAGE_SIZE:
                page_size = MAX_PAGE_SIZE
        except (ValueError, TypeError):
            page_size = DEFAULT_PAGE_SIZE

        # Filter: unread / read / status
        unread_raw = params.get("unread")
        is_read_raw = params.get("is_read")
        unread_only = None

        if unread_raw is not None:
            if isinstance(unread_raw, bool):
                unread_only = unread_raw
            elif str(unread_raw).lower() in ("true", "1", "yes"):
                unread_only = True
            elif str(unread_raw).lower() in ("false", "0", "no"):
                unread_only = False

        if unread_only is None and is_read_raw is not None:
            if isinstance(is_read_raw, bool):
                unread_only = not is_read_raw
            elif str(is_read_raw).lower() in ("true", "1", "yes"):
                unread_only = False
            elif str(is_read_raw).lower() in ("false", "0", "no"):
                unread_only = True

        # Priority filter
        priority = params.get("priority")
        if priority and priority not in ALLOWED_NOTIFICATION_PRIORITIES:
            raise ATSValidationError(
                f"Invalid priority filter '{priority}'. Allowed values: {', '.join(ALLOWED_NOTIFICATION_PRIORITIES)}.",
                field="priority",
            )

        # Notification type filter
        notification_type = params.get("notification_type") or params.get("type")
        if notification_type and notification_type not in ALLOWED_NOTIFICATION_TYPES:
            raise ATSValidationError(
                f"Invalid type filter '{notification_type}'. Allowed values: {', '.join(ALLOWED_NOTIFICATION_TYPES)}.",
                field="notification_type",
            )

        category = params.get("category")

        # Sorting
        allowed_sort_fields = {"creation", "priority", "is_read", "title", "notification_type"}
        order_by = params.get("order_by", "creation")
        if order_by not in allowed_sort_fields:
            order_by = "creation"

        order_dir = str(params.get("order_dir", "desc")).lower()
        if order_dir not in ("asc", "desc"):
            order_dir = "desc"

        search = str(params.get("search", "")).strip()

        return {
            "page": page,
            "page_size": page_size,
            "unread_only": unread_only,
            "priority": priority,
            "notification_type": notification_type,
            "category": category,
            "search": search,
            "order_by": order_by,
            "order_dir": order_dir,
            "from_date": params.get("from_date"),
            "to_date": params.get("to_date"),
        }

    @staticmethod
    def validate_preferences(preferences: dict[str, Any]) -> dict[str, bool]:
        """Validate user notification preference dictionary.

        Parameters
        ----------
        preferences : dict
            Mapping of preference flags.

        Returns
        -------
        dict
            Sanitised dictionary mapping setting keys to booleans.

        Raises
        ------
        ATSValidationError
            If input is not a dictionary.
        """
        if not isinstance(preferences, dict):
            raise ATSValidationError("Preferences payload must be a JSON object.")

        sanitised: dict[str, bool] = {}
        for key, val in preferences.items():
            if not isinstance(key, str):
                continue
            if isinstance(val, bool):
                sanitised[key] = val
            elif str(val).lower() in ("true", "1", "yes"):
                sanitised[key] = True
            elif str(val).lower() in ("false", "0", "no"):
                sanitised[key] = False

        return sanitised
