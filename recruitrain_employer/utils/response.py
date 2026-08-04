# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.utils.response
=====================================

Standardised API Response Builders with HTTP Status Code Mapping.

All API endpoints in ``recruitrain_employer.api`` MUST use these helpers to
ensure a consistent response envelope and correct HTTP status code header.
"""

from __future__ import annotations

import math
from typing import Any

import frappe

STATUS_CODE_MAP: dict[str, int] = {
    "VALIDATION_ERROR": 400,
    "AUTHENTICATION_ERROR": 401,
    "PERMISSION_DENIED": 403,
    "NOT_FOUND": 404,
    "CONFLICT": 409,
    "INTERNAL_ERROR": 500,
}


def success_response(data: Any = None, message: str = "") -> dict:
    """Build a standardised success response envelope."""
    if hasattr(frappe, "response"):
        frappe.response["http_status_code"] = 200

    response: dict[str, Any] = {
        "success": True,
        "data": data,
    }
    if message:
        response["message"] = message
    return response


def error_response(code: str, message: str, details: Any = None, http_status_code: int | None = None) -> dict:
    """Build a standardised error response envelope and set HTTP status code."""
    status_code = http_status_code or STATUS_CODE_MAP.get(code, 400)
    if hasattr(frappe, "response"):
        frappe.response["http_status_code"] = status_code

    error_body: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if details is not None:
        error_body["details"] = details

    return {
        "success": False,
        "error": error_body,
    }


def paginated_response(data: list, page: int, page_size: int, total: int) -> dict:
    """Build a standardised paginated success response envelope."""
    if hasattr(frappe, "response"):
        frappe.response["http_status_code"] = 200

    total_pages = math.ceil(total / page_size) if page_size > 0 else 0

    return {
        "success": True,
        "data": data,
        "meta": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        },
    }


def not_found_response(doctype: str, name: str) -> dict:
    """Shortcut to build a NOT_FOUND error response (HTTP 404)."""
    return error_response(
        code="NOT_FOUND",
        message=f"{doctype} '{name}' was not found.",
        details={"doctype": doctype, "name": name},
        http_status_code=404,
    )


def permission_denied_response(reason: str = "") -> dict:
    """Shortcut to build a PERMISSION_DENIED error response (HTTP 403)."""
    message = reason if reason else "You do not have permission to perform this action."
    return error_response(
        code="PERMISSION_DENIED",
        message=message,
        http_status_code=403,
    )
