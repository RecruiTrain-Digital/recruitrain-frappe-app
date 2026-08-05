# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api.profile
=================================

Employer Profile Management API Endpoints.

Architecture
------------
This module is a **thin controller layer only**.
All business logic, DocType interactions, file storage, and persistence operations
live in ``ProfileService``.

Request/Response Flow::

    React Frontend
          │
          ▼
    api/profile.py       ← Parse request, invoke ProfileService, wrap in standard JSON response
          │
          ▼
    ProfileService       ← All business logic & Frappe interactions
          │
          ▼
    ProfileValidator     ← Data sanitisation and validation
          │
          ▼
    Frappe ORM (Employer User, Company, File, User)

Endpoint Path Prefix
---------------------
/api/method/recruitrain_employer.api.profile.<function_name>
"""

from __future__ import annotations

import frappe
from recruitrain_employer.services.profile_service import ProfileService
from recruitrain_employer.utils.permissions import employer_required
from recruitrain_employer.utils.exceptions import ATSException, ATSValidationError
from recruitrain_employer.utils.response import error_response, success_response


def _handle_ats_exception(exc: ATSException) -> dict:
    """Translate an ``ATSException`` into a standardised error response dict."""
    return error_response(
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


@frappe.whitelist()
@employer_required
def get_profile() -> dict:
    """Retrieve the full Employer Profile for the currently authenticated user.

    Returns
    -------
    dict
        Standardised success response containing Employer information,
        Company information, Avatar URL, Role, Designation, Contact details,
        and Preferences.
    """
    try:
        service = ProfileService()
        profile_data = service.get_profile()
        return success_response(data=profile_data, message="Employer profile retrieved successfully.")
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def update_profile() -> dict:
    """Update mutable fields of the Employer Profile for the authenticated user.

    Supports partial updates. Only updates changed fields. Does not overwrite
    existing values with null.

    Security: User is resolved strictly from session to prevent IDOR vulnerabilities.

    Returns
    -------
    dict
        Standardised success response with updated profile data.
    """
    try:
        data = frappe.request.get_json() if (frappe.request and frappe.request.get_json()) else frappe.form_dict
        service = ProfileService()
        updated_profile = service.update_profile(data=data)
        return success_response(data=updated_profile, message="Employer profile updated successfully.")
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def upload_profile_photo() -> dict:
    """Upload or replace the Employer profile photo.

    Accepts multipart/form-data. Stores file using Frappe File DocType, attaches it
    to Employer User, and returns absolute URLs and metadata.

    Expected Request:
        Multipart form-data with file field named 'file', 'image', 'photo', or 'avatar'.

    Returns
    -------
    dict
        Standardised success response containing file_url, thumbnail, and image metadata.
    """
    try:
        file_obj = None
        if hasattr(frappe.request, "files") and frappe.request.files:
            files_dict = frappe.request.files
            for key in ("file", "image", "photo", "avatar"):
                if key in files_dict:
                    file_obj = files_dict[key]
                    break
            if not file_obj and len(files_dict) > 0:
                file_obj = list(files_dict.values())[0]

        if not file_obj or not getattr(file_obj, "filename", None):
            raise ATSValidationError(
                "No photo file provided. Send a multipart/form-data request with a file field.",
                field="file",
            )

        file_name = file_obj.filename
        file_content = file_obj.read()
        content_type = getattr(file_obj, "content_type", None) or frappe.form_dict.get("content_type")

        service = ProfileService()
        result = service.upload_profile_photo(
            file_content=file_content,
            file_name=file_name,
            content_type=content_type,
        )

        return success_response(data=result, message="Profile photo uploaded successfully.")
    except ATSException as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def remove_profile_photo() -> dict:
    """Delete the profile photo attachment and clear avatar reference.

    Returns
    -------
    dict
        Standardised success response confirming attachment deletion.
    """
    try:
        service = ProfileService()
        result = service.remove_profile_photo()
        return success_response(data=result, message="Profile photo removed successfully.")
    except ATSException as exc:
        return _handle_ats_exception(exc)
