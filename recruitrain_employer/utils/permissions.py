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

from recruitrain_employer.utils.constants import DOCTYPE_COMPANY, DOCTYPE_EMPLOYER_USER
from recruitrain_employer.utils.exceptions import ATSCompanyNotFoundError, ATSPermissionError

# Role hierarchy maps Employer User DocType ``role`` field options to privilege levels.
ROLE_HIERARCHY: dict[str, int] = {
    "Administrator": 100,
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

    # Check for an active Employer User record for this user
    records = frappe.get_all(
        DOCTYPE_EMPLOYER_USER,
        filters={"user": user, "status": "Active"},
        fields=["name", "user", "company", "role", "department", "designation", "status"],
        limit=1,
    )

    if records:
        rec = records[0]
        if not rec.get("company"):
            raise ATSCompanyNotFoundError(
                f"No company associated with active employer user '{user}'.",
                details={"user": user},
            )
        return rec

    # Administrator session fallback — query existing active Company record from DB
    if user == "Administrator":
        active_company = (
            frappe.db.get_value(DOCTYPE_COMPANY, {"status": "Active"}, "name")
            or frappe.db.get_value(DOCTYPE_COMPANY, {}, "name")
        )
        if not active_company:
            raise ATSCompanyNotFoundError(
                "No active Company record exists in database for Administrator.",
                details={"user": user},
            )
        return {
            "name": "Administrator",
            "user": "Administrator",
            "company": active_company,
            "role": "Administrator",
            "status": "Active",
        }

    raise ATSCompanyNotFoundError(
        f"User '{user}' is not registered as an active Employer User.",
        details={"user": user},
    )


def get_current_company() -> str:
    """Return the validated active company name for the currently authenticated employer user.

    Single Source of Truth for Company resolution across the entire backend.

    Resolution Pipeline:
    Current authenticated user -> Employer User.company -> Company DocType (validated existing & active)

    Returns
    -------
    str
        The canonical company name.

    Raises
    ------
    ATSCompanyNotFoundError
        If no company is associated with the user, or if the company does not exist or is inactive.
    """
    user_info = get_current_employer_user()
    company = user_info.get("company")
    if not company:
        raise ATSCompanyNotFoundError("No company associated with current authenticated employer user.")

    # Validate company exists in Company DocType
    if not frappe.db.exists(DOCTYPE_COMPANY, company):
        raise ATSCompanyNotFoundError(
            f"Company '{company}' associated with current user does not exist.",
            details={"company": company},
        )

    # Validate company status is active
    status = frappe.db.get_value(DOCTYPE_COMPANY, company, "status")
    if status and status != "Active":
        raise ATSCompanyNotFoundError(
            f"Company '{company}' is inactive.",
            details={"company": company, "status": status},
        )

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
    """Assert the current user has the Administrator role (highest privilege)."""
    require_role("Administrator")


def employer_required(func: Callable) -> Callable:
    """Decorator: ensures the caller is an authenticated Employer User."""
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            get_current_employer_user()
        except (ATSPermissionError, ATSCompanyNotFoundError) as exc:
            from recruitrain_employer.utils.response import error_response
            status_code = 401 if (isinstance(exc, ATSPermissionError) or "Authentication" in str(exc) or "log in" in str(exc)) else 403
            code = "UNAUTHORIZED" if status_code == 401 else getattr(exc, "code", "PERMISSION_DENIED")
            return error_response(
                code=code,
                message=getattr(exc, "message", str(exc)),
                details=getattr(exc, "details", None),
                http_status_code=status_code,
            )
        return func(*args, **kwargs)
    return wrapper


def admin_required(func: Callable) -> Callable:
    """Decorator: ensures the caller has the Employer Admin role."""
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        require_admin()
        return func(*args, **kwargs)
    return wrapper
