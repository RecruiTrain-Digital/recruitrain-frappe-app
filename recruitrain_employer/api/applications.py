# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api.applications
========================================

.. deprecated:: 1.0
   Use ``recruitrain_employer.api.job_application`` instead.

This module is maintained for backward compatibility and delegates all calls
to ``recruitrain_employer.api.job_application``.
"""

from __future__ import annotations

import warnings
import frappe

from recruitrain_employer.api.job_application import (
    create_application as _create,
    get_application as _get,
    list_applications as _list,
    update_application as _update,
    delete_application as _delete,
    change_status as _status,
    search_applications as _search,
)

warnings.warn(
    "recruitrain_employer.api.applications is deprecated. Use recruitrain_employer.api.job_application instead.",
    DeprecationWarning,
    stacklevel=2,
)


@frappe.whitelist()
def create_application() -> dict:
    """Delegates to job_application.create_application."""
    return _create()


@frappe.whitelist()
def get_application(application_id: str | None = None) -> dict:
    """Delegates to job_application.get_application."""
    return _get(application_id=application_id)


@frappe.whitelist()
def list_applications() -> dict:
    """Delegates to job_application.list_applications."""
    return _list()


@frappe.whitelist()
def update_application(application_id: str | None = None) -> dict:
    """Delegates to job_application.update_application."""
    return _update(application_id=application_id)


@frappe.whitelist()
def delete_application(application_id: str | None = None) -> dict:
    """Delegates to job_application.delete_application."""
    return _delete(application_id=application_id)


@frappe.whitelist()
def change_status(application_id: str | None = None, new_status: str | None = None) -> dict:
    """Delegates to job_application.change_status."""
    return _status(application_id=application_id, new_status=new_status)


@frappe.whitelist()
def search_applications() -> dict:
    """Delegates to job_application.search_applications."""
    return _search()
