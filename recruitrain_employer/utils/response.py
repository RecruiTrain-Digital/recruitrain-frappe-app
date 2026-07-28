# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.utils.response
=====================================

Standardised API Response Builders.

All API endpoints in ``recruitrain_employer.api`` MUST use these helpers to
ensure a consistent response envelope across all endpoints.

Response Envelope Format
------------------------

Success::

    {
        "success": true,
        "data": <payload>,
        "message": "<optional human-readable message>"
    }

Error::

    {
        "success": false,
        "error": {
            "code": "<ERROR_CODE>",
            "message": "<human-readable message>",
            "details": <optional extra context>
        }
    }

Paginated Success::

    {
        "success": true,
        "data": [...],
        "meta": {
            "page": <int>,
            "page_size": <int>,
            "total": <int>,
            "total_pages": <int>
        }
    }
"""

from __future__ import annotations

import math
from typing import Any


def success_response(data: Any = None, message: str = "") -> dict:
    """Build a standardised success response envelope.

    Parameters
    ----------
    data : Any, optional
        The payload to include in the ``data`` key.  Can be a dict, list,
        string, or ``None``.
    message : str, optional
        A human-readable status message (e.g. ``"Record created successfully"``).

    Returns
    -------
    dict
        A response dict ready to be returned from a ``@frappe.whitelist()`` endpoint.

    Example
    -------
    >>> success_response({"name": "JOB-0001"}, "Job Opening created.")
    {"success": True, "data": {"name": "JOB-0001"}, "message": "Job Opening created."}
    """
    response: dict[str, Any] = {
        "success": True,
        "data": data,
    }
    if message:
        response["message"] = message
    return response


def error_response(code: str, message: str, details: Any = None) -> dict:
    """Build a standardised error response envelope.

    Parameters
    ----------
    code : str
        A machine-readable error code (e.g. ``"VALIDATION_ERROR"``,
        ``"NOT_FOUND"``, ``"PERMISSION_DENIED"``).
    message : str
        A human-readable error description.
    details : Any, optional
        Additional context (e.g. field-level validation errors as a dict).

    Returns
    -------
    dict
        A response dict ready to be returned from a ``@frappe.whitelist()`` endpoint.

    Example
    -------
    >>> error_response("VALIDATION_ERROR", "Email is required.", {"field": "email"})
    {
        "success": False,
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Email is required.",
            "details": {"field": "email"}
        }
    }
    """
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
    """Build a standardised paginated success response envelope.

    Parameters
    ----------
    data : list
        The list of records for the current page.
    page : int
        The current page number (1-indexed).
    page_size : int
        Number of records per page.
    total : int
        Total number of matching records across all pages.

    Returns
    -------
    dict
        A response dict with ``data`` and ``meta`` pagination info.

    Example
    -------
    >>> paginated_response([...], page=1, page_size=20, total=45)
    {
        "success": True,
        "data": [...],
        "meta": {
            "page": 1,
            "page_size": 20,
            "total": 45,
            "total_pages": 3
        }
    }
    """
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
    """Shortcut to build a NOT_FOUND error response.

    Parameters
    ----------
    doctype : str
        The DocType that was not found (e.g. ``"Job Opening"``).
    name : str
        The name/ID that was looked up.

    Returns
    -------
    dict
        An error response with code ``"NOT_FOUND"``.
    """
    return error_response(
        code="NOT_FOUND",
        message=f"{doctype} '{name}' was not found.",
        details={"doctype": doctype, "name": name},
    )


def permission_denied_response(reason: str = "") -> dict:
    """Shortcut to build a PERMISSION_DENIED error response.

    Parameters
    ----------
    reason : str, optional
        Additional context about why access was denied.

    Returns
    -------
    dict
        An error response with code ``"PERMISSION_DENIED"``.
    """
    message = reason if reason else "You do not have permission to perform this action."
    return error_response(
        code="PERMISSION_DENIED",
        message=message,
    )
