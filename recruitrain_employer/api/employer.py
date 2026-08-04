# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api.employer
===================================

Employer User Management API Endpoints.
"""

from __future__ import annotations

import frappe
from recruitrain_employer.services.employer_service import EmployerService
from recruitrain_employer.utils.decorators import employer_required
from recruitrain_employer.utils.response import success_response


@frappe.whitelist()
@employer_required
def get_employer_user(employer_user_id: str):
    """Retrieve an Employer User record by ID."""
    svc = EmployerService()
    user = svc.get_employer_user(employer_user_id)
    return success_response(data=user, message="Employer user retrieved successfully.")


@frappe.whitelist()
@employer_required
def update_employer_user(employer_user_id: str):
    """Update mutable fields of an existing Employer User record."""
    data = frappe.request.get_json() if frappe.request and frappe.request.get_json() else frappe.form_dict
    svc = EmployerService()
    user = svc.update_employer_user(employer_user_id, data)
    return success_response(data=user, message="Employer user updated successfully.")


@frappe.whitelist()
@employer_required
def list_employer_users():
    """Return a paginated list of Employer Users for the current company."""
    params = frappe.request.get_json() if frappe.request and frappe.request.get_json() else frappe.form_dict
    svc = EmployerService()
    result = svc.list_employer_users(filters=params, pagination=params)
    return success_response(
        data=result.get("data", []),
        meta={
            "total": result.get("total", 0),
            "page": result.get("page", 1),
            "page_size": result.get("page_size", 20),
        },
        message="Employer users listed successfully.",
    )


@frappe.whitelist()
@employer_required
def invite_team_member():
    """Invite a new team member by sending an invitation email."""
    data = frappe.request.get_json() if frappe.request and frappe.request.get_json() else frappe.form_dict
    email = data.get("email")
    role = data.get("role")
    company = getattr(frappe.flags, "employer_company", "RecruiTrain")

    svc = EmployerService()
    result = svc.invite_team_member(email=email, role=role, company=company)
    return success_response(data=result, message="Team member invited successfully.")


@frappe.whitelist()
@employer_required
def deactivate_employer_user(employer_user_id: str):
    """Deactivate an Employer User, revoking system access."""
    svc = EmployerService()
    result = svc.deactivate_employer_user(employer_user_id)
    return success_response(data=result, message="Employer user deactivated successfully.")


@frappe.whitelist()
@employer_required
def update_employer_role(employer_user_id: str):
    """Change the role of an Employer User within the company."""
    data = frappe.request.get_json() if frappe.request and frappe.request.get_json() else frappe.form_dict
    role = data.get("role")
    svc = EmployerService()
    result = svc.update_employer_role(employer_user_id, role)
    return success_response(data=result, message="Employer role updated successfully.")
