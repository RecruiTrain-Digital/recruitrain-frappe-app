# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.utils.permissions
=========================================

Role & Ownership-Based Permission Check Utilities.

This module provides decorator functions and helper utilities for enforcing
access control in service methods and API endpoints.

Permission Model
----------------
The ATS uses a three-tier permission model:

1. **Frappe Role Permissions** — handled automatically by the Frappe framework
   for DocType-level CRUD via ``frappe.has_permission()``.
2. **Company Scoping** — all employer-facing data is scoped to the company
   the authenticated Employer User belongs to.
3. **Record Ownership** — certain records can only be accessed or modified
   by their owner or authorized role.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable

import frappe

from recruitrain_employer.utils.constants import DOCTYPE_EMPLOYER_USER
from recruitrain_employer.utils.exceptions import ATSPermissionError

ROLE_HIERARCHY: dict[str, int] = {
    "Administrator": 100,
    "Employer Admin": 90,
    "HR Manager": 80,
    "Recruiter": 70,
    "Hiring Manager": 60,
    "Interviewer": 50,
    "Viewer": 10,
}


def get_current_employer_user() -> dict:
    """Return the Employer User record for the currently authenticated user."""
    user = getattr(frappe.session, "user", None) or "Guest"

    if user == "Guest":
        raise ATSPermissionError("Authentication required. Please log in.")

    # Administrator session fallback
    if user == "Administrator":
        return {
            "user": "Administrator",
            "company": "Default Company",
            "role": "Employer Admin",
            "status": "Active",
        }

    records = frappe.get_all(
        DOCTYPE_EMPLOYER_USER,
        filters={"user": user, "status": "Active"},
        fields=["name", "user", "company", "role", "department", "designation", "status"],
        limit=1,
    )

    if not records:
        raise ATSPermissionError(
            f"User '{user}' is not registered as an active Employer User.",
            details={"user": user},
        )

    return records[0]


def get_current_company() -> str:
    """Return the company name associated with the currently authenticated employer user."""
    user_info = get_current_employer_user()
    company = user_info.get("company")
    if not company:
        raise ATSPermissionError("No company assigned to current employer user.")
    return company


def has_role(role: str) -> bool:
    """Check whether the currently authenticated user has the specified employer role."""
    try:
        user_info = get_current_employer_user()
        user_role = user_info.get("role", "Viewer")
        user_level = ROLE_HIERARCHY.get(user_role, 0)
        required_level = ROLE_HIERARCHY.get(role, 0)
        return user_level >= required_level
    except ATSPermissionError:
        return False


def is_company_member(company: str) -> bool:
    """Check whether the currently authenticated user belongs to the given company."""
    try:
        user_company = get_current_company()
        return user_company == company or getattr(frappe.session, "user", "") == "Administrator"
    except ATSPermissionError:
        return False


def require_role(required_role: str) -> None:
    """Assert the current user has the required employer role."""
    if not has_role(required_role):
        raise ATSPermissionError(
            f"Role '{required_role}' is required to perform this action.",
            required_role=required_role,
        )


def require_company_member(company: str) -> None:
    """Assert the current user belongs to the specified company."""
    if not is_company_member(company):
        raise ATSPermissionError(
            f"Access denied. You do not belong to company '{company}'.",
            details={"company": company},
        )


def require_admin() -> None:
    """Assert the current user has the Employer Admin role."""
    require_role("Employer Admin")


def employer_required(func: Callable) -> Callable:
    """Decorator: ensures the caller is an authenticated Employer User."""
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        get_current_employer_user()
        return func(*args, **kwargs)
    return wrapper


def admin_required(func: Callable) -> Callable:
    """Decorator: ensures the caller has the Employer Admin role."""
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        require_admin()
        return func(*args, **kwargs)
    return wrapper
