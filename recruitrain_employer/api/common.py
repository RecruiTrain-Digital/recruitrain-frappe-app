# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api.common
==================================

Shared Utility API Endpoints.
"""

from __future__ import annotations

import frappe
from recruitrain_employer.utils.response import success_response

from recruitrain_employer.validators.department_validator import DepartmentResolver, seed_default_departments
from recruitrain_employer.validators.employment_type_validator import seed_default_employment_types
from recruitrain_employer.validators.industry_validator import seed_default_industries
from recruitrain_employer.validators.profession_validator import seed_default_professions


@frappe.whitelist(allow_guest=True)
def health_check():
    """Simple liveness probe endpoint."""
    return success_response(
        data={"status": "ok", "app": "recruitrain_employer"},
        message="Application is healthy.",
    )


@frappe.whitelist(allow_guest=True)
def get_app_version():
    """Return the installed version of the recruitrain_employer app."""
    version = frappe.get_attr("recruitrain_employer.__version__") if hasattr(frappe.get_module("recruitrain_employer"), "__version__") else "1.0.0"
    return success_response(
        data={"version": version},
        message="App version retrieved.",
    )


@frappe.whitelist(allow_guest=True)
def get_skills():
    """Return the full list of Skill master records for autocomplete."""
    search = frappe.form_dict.get("search", "")
    filters = [["name", "like", f"%{search}%"]] if search else []
    skills = frappe.get_all("Skill", filters=filters, fields=["name"], order_by="name asc")
    return success_response(data=[s["name"] for s in skills], message="Skills retrieved.")


@frappe.whitelist(allow_guest=True)
def list_professions(department: str | None = None):
    """Return list of Profession master records, filtered by parent Department if provided."""
    try:
        seed_default_professions()
    except Exception:
        pass

    dept_param = department or frappe.form_dict.get("department")
    filters = {"is_active": 1}

    if dept_param and str(dept_param).strip():
        try:
            canonical_dept = DepartmentResolver.resolve(str(dept_param))
            filters["department"] = canonical_dept
        except Exception:
            return success_response(data=[], message="No professions found for specified department.")

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
    return success_response(data=data, message="Professions retrieved.")


@frappe.whitelist(allow_guest=True)
def get_professions(department: str | None = None):
    """Alias for list_professions."""
    return list_professions(department=department)


@frappe.whitelist(allow_guest=True)
def list_employment_types():
    """Return the full list of Employment Type master records."""
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
    return success_response(data=data, message="Employment types retrieved.")


@frappe.whitelist(allow_guest=True)
def get_employment_types():
    """Alias for list_employment_types."""
    return list_employment_types()


@frappe.whitelist(allow_guest=True)
def list_industries():
    """Return the full list of Industry master records."""
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
    return success_response(data=data, message="Industries retrieved.")


@frappe.whitelist(allow_guest=True)
def get_industries():
    """Alias for list_industries."""
    return list_industries()


@frappe.whitelist(allow_guest=True)
def list_departments():
    """Return list of Department master records."""
    try:
        seed_default_departments()
    except Exception:
        pass
    records = frappe.get_all("Department", fields=["name", "department_name"], order_by="name asc")
    data = [
        {
            "id": r.get("name"),
            "name": r.get("name"),
            "display_name": r.get("department_name") or r.get("name"),
        }
        for r in records
    ]
    return success_response(data=data, message="Departments retrieved.")


@frappe.whitelist(allow_guest=True)
def get_departments():
    """Alias for list_departments."""
    return list_departments()


@frappe.whitelist()
def upload_file():
    """Generic file upload endpoint used across multiple DocTypes."""
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": frappe.form_dict.get("filename", "upload"),
        "attached_to_doctype": frappe.form_dict.get("doctype"),
        "attached_to_name": frappe.form_dict.get("docname"),
        "attached_to_field": frappe.form_dict.get("fieldname"),
        "is_private": int(frappe.form_dict.get("is_private", 1)),
        "content": frappe.request.files.get("file").read() if frappe.request and frappe.request.files and "file" in frappe.request.files else None,
    })
    if file_doc.content:
        file_doc.insert(ignore_permissions=True)
    return success_response(
        data={"file_url": file_doc.file_url or "/files/upload"},
        message="File uploaded successfully.",
    )
