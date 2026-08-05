# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api.master
===============================

Master Taxonomy Data API Endpoints (Department, Profession, Employment Type, Industry).
"""

from __future__ import annotations

import frappe

from recruitrain_employer.utils.response import success_response
from recruitrain_employer.validators.department_validator import DepartmentResolver, seed_default_departments
from recruitrain_employer.validators.employment_type_validator import seed_default_employment_types
from recruitrain_employer.validators.industry_validator import seed_default_industries
from recruitrain_employer.validators.profession_validator import seed_default_professions


@frappe.whitelist(allow_guest=True)
def list_departments() -> dict:
    """Return list of canonical Department taxonomy records.

    Returns
    -------
    dict
        Standardized success response containing list of dicts with:
        id, name, display_name.
    """
    try:
        seed_default_departments()
    except Exception as exc:
        frappe.logger().error(f"[Master API] Department seed error: {exc}")

    records = frappe.get_all(
        "Department",
        fields=["name", "department_name"],
        order_by="name asc",
    )

    data = [
        {
            "id": r.get("name"),
            "name": r.get("name"),
            "display_name": r.get("department_name") or r.get("name"),
        }
        for r in records
    ]

    return success_response(data=data, message="Departments retrieved successfully.")


@frappe.whitelist(allow_guest=True)
def get_departments() -> dict:
    """Alias for list_departments."""
    return list_departments()


@frappe.whitelist(allow_guest=True)
def list_professions(department: str | None = None) -> dict:
    """Return list of Profession taxonomy records, optionally filtered by parent Department.

    Parameters
    ----------
    department : str, optional
        Department name or alias (e.g., 'Healthcare' or 'health-care').
        When specified, strictly filters professions belonging to that department.
        Never returns unrelated professions.

    Returns
    -------
    dict
        Standardized success response containing list of dicts with:
        id, name, display_name, department, description, display_order.
    """
    try:
        seed_default_professions()
    except Exception as exc:
        frappe.logger().error(f"[Master API] Profession seed error: {exc}")

    dept_param = department or frappe.form_dict.get("department")
    filters = {"is_active": 1}

    if dept_param and str(dept_param).strip():
        try:
            canonical_dept = DepartmentResolver.resolve(str(dept_param))
            filters["department"] = canonical_dept
        except Exception:
            return success_response(
                data=[],
                message="No professions found for specified department.",
            )

    records = frappe.get_all(
        "Profession",
        filters=filters,
        fields=["name", "profession_name", "department", "description", "display_order"],
        order_by="display_order asc, profession_name asc",
    )

    data = [
        {
            "id": r.get("name"),
            "name": r.get("name"),
            "display_name": r.get("profession_name") or r.get("name"),
            "department": r.get("department"),
            "description": r.get("description"),
            "display_order": r.get("display_order", 0),
        }
        for r in records
    ]

    return success_response(data=data, message="Professions retrieved successfully.")


@frappe.whitelist(allow_guest=True)
def get_professions(department: str | None = None) -> dict:
    """Alias for list_professions."""
    return list_professions(department=department)


@frappe.whitelist(allow_guest=True)
def list_employment_types() -> dict:
    """Return full list of canonical Employment Type records."""
    try:
        seed_default_employment_types()
    except Exception:
        pass
    records = frappe.get_all("Employment Type", fields=["name", "employment_type_name"], order_by="name asc")
    data = [
        {
            "id": r.get("name"),
            "name": r.get("name"),
            "display_name": r.get("employment_type_name") or r.get("name"),
        }
        for r in records
    ]
    return success_response(data=data, message="Employment types retrieved successfully.")


@frappe.whitelist(allow_guest=True)
def list_industries() -> dict:
    """Return full list of canonical Industry records."""
    try:
        seed_default_industries()
    except Exception:
        pass
    records = frappe.get_all("Industry", fields=["name", "industry_name"], order_by="name asc")
    data = [
        {
            "id": r.get("name"),
            "name": r.get("name"),
            "display_name": r.get("industry_name") or r.get("name"),
        }
        for r in records
    ]
    return success_response(data=data, message="Industries retrieved successfully.")
