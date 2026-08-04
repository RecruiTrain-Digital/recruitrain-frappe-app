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
def get_professions():
    """Return the full list of Profession master records."""
    records = frappe.get_all("Profession", fields=["name"], order_by="name asc")
    return success_response(data=[r["name"] for r in records], message="Professions retrieved.")


@frappe.whitelist(allow_guest=True)
def get_employment_types():
    """Return the full list of Employment Type master records."""
    records = frappe.get_all("Employment Type", fields=["name"], order_by="name asc")
    return success_response(data=[r["name"] for r in records], message="Employment types retrieved.")


@frappe.whitelist(allow_guest=True)
def get_industries():
    """Return the full list of Industry master records."""
    records = frappe.get_all("Industry", fields=["name"], order_by="name asc")
    return success_response(data=[r["name"] for r in records], message="Industries retrieved.")


@frappe.whitelist(allow_guest=True)
def get_departments():
    """Return the full list of Department master records."""
    records = frappe.get_all("Department", fields=["name"], order_by="name asc")
    return success_response(data=[r["name"] for r in records], message="Departments retrieved.")


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
