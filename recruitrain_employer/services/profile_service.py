# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.services.profile_service
===============================================

Employer Profile Business Logic Service.

Owns all business logic related to:
- Retrieving composite Employer User + User + Company profile
- Processing partial profile updates with persistence
- Managing profile avatar uploads using Frappe File DocType
- Deleting profile photo attachments and references

Canonical Source of Truth:
- Employer User (DocType)
- Company (DocType)
- File (Frappe DocType)
"""

from __future__ import annotations

import mimetypes
import frappe
from frappe.utils import get_url

from recruitrain_employer.utils.constants import (
    DOCTYPE_COMPANY,
    DOCTYPE_EMPLOYER_USER,
    MAX_FILE_SIZE_BYTES,
)
from recruitrain_employer.utils.exceptions import (
    ATSNotFoundError,
    ATSPermissionError,
    ATSValidationError,
)
from recruitrain_employer.utils.permissions import get_current_employer_user
from recruitrain_employer.validators.profile_validator import ProfileValidator

ALLOWED_IMAGE_MIMES = frozenset([
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
])

ALLOWED_IMAGE_EXTENSIONS = frozenset([
    ".png", ".jpg", ".jpeg", ".webp"
])


class ProfileService:
    """Encapsulates business logic for Employer Profile operations."""

    def __init__(self) -> None:
        self.validator = ProfileValidator()

    # ------------------------------------------------------------------
    # Notification Helper
    # ------------------------------------------------------------------

    @staticmethod
    def _notify(title: str, message: str, company: str, recipient: str, entity_id: str) -> None:
        """Send asynchronous in-app notification upon profile updates."""
        try:
            from recruitrain_employer.services.notification_service import NotificationService
            ns = NotificationService()
            ns.create_notification(
                raw_data={
                    "title": title,
                    "message": message,
                    "notification_type": "System",
                    "priority": "Low",
                    "category": "System",
                    "entity_type": "Employer User",
                    "entity_id": entity_id,
                    "action_url": "/profile",
                    "action_label": "View Profile",
                },
                company=company,
                recipient=recipient,
                created_by=getattr(frappe.session, "user", "System"),
            )
        except Exception as exc:
            frappe.logger().error(f"Profile notification error: {exc}")

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _get_active_employer_user_doc(self):
        """Resolve and return the current authenticated user's Employer User document.
        
        Security requirement: User is resolved strictly from session. Never trust profile_id
        from the frontend to prevent IDOR attacks.
        """
        emp_info = get_current_employer_user()
        emp_user_name = emp_info.get("name")

        if not emp_user_name or not frappe.db.exists(DOCTYPE_EMPLOYER_USER, emp_user_name):
            raise ATSNotFoundError(
                f"Employer User record not found for active user.",
                doctype=DOCTYPE_EMPLOYER_USER,
            )

        return frappe.get_doc(DOCTYPE_EMPLOYER_USER, emp_user_name)

    def _get_absolute_url(self, relative_path: str | None) -> str | None:
        """Convert a relative file path or URL to an absolute URL."""
        if not relative_path:
            return None
        if relative_path.startswith("http://") or relative_path.startswith("https://"):
            return relative_path
        return get_url(relative_path)

    # ------------------------------------------------------------------
    # Profile GET
    # ------------------------------------------------------------------

    def get_profile(self) -> dict:
        """Retrieve the complete, canonical profile for the current authenticated Employer User."""
        emp_doc = self._get_active_employer_user_doc()
        user_id = emp_doc.user

        # Fetch underlying Frappe User doc
        user_doc = frappe.get_doc("User", user_id) if frappe.db.exists("User", user_id) else None

        # Fetch Company doc
        company_id = emp_doc.company
        self.validator.validate_company(company_id)
        company_doc = frappe.get_doc(DOCTYPE_COMPANY, company_id) if frappe.db.exists(DOCTYPE_COMPANY, company_id) else None

        # Resolve avatar URL
        avatar_path = emp_doc.get("avatar") or (user_doc.get("user_image") if user_doc else None)
        avatar_url = self._get_absolute_url(avatar_path)

        # Resolve Company Logo URL
        logo_path = company_doc.get("logo") if company_doc else None
        logo_url = self._get_absolute_url(logo_path)

        # First / Last / Full name resolution
        first_name = emp_doc.get("first_name") or (user_doc.first_name if user_doc else "")
        last_name = emp_doc.get("last_name") or (user_doc.last_name if user_doc else "")
        full_name = emp_doc.get("full_name") or (user_doc.full_name if user_doc else f"{first_name} {last_name}".strip())

        # Phone resolution
        phone = emp_doc.get("phone") or (user_doc.get("mobile_no") or user_doc.get("phone") if user_doc else "") or (company_doc.get("phone") if company_doc else "")

        # Bio resolution
        bio = emp_doc.get("bio") or (user_doc.get("bio") if user_doc else "")

        # Preferences resolution
        timezone = emp_doc.get("timezone") or (user_doc.get("time_zone") if user_doc else None) or (company_doc.get("timezone") if company_doc else "UTC")
        language = emp_doc.get("language") or (user_doc.get("language") if user_doc else None) or (company_doc.get("language") if company_doc else "en")

        # Location resolution
        city = emp_doc.get("city") or (company_doc.get("city") if company_doc else "")
        state = emp_doc.get("state") or (company_doc.get("state") if company_doc else "")
        country = emp_doc.get("country") or (company_doc.get("country") if company_doc else "")
        location_parts = [p for p in [city, state, country] if p]
        location_str = ", ".join(location_parts) if location_parts else ""

        # Notification Preferences parsing
        notification_prefs = emp_doc.get("notification_preferences")
        if isinstance(notification_prefs, str) and notification_prefs:
            try:
                notification_prefs = frappe.parse_json(notification_prefs)
            except Exception as exc:
                frappe.logger().warning(f"Failed to parse notification_preferences JSON: {exc}")

        employer_data = {
            "id": emp_doc.name,
            "user": user_id,
            "first_name": first_name,
            "last_name": last_name,
            "full_name": full_name,
            "email": user_doc.email if user_doc else user_id,
            "phone": phone,
            "designation": emp_doc.get("designation") or "",
            "department": emp_doc.get("department") or "",
            "employee_id": emp_doc.get("employee_id") or "",
            "bio": bio,
            "role": emp_doc.get("role") or "Viewer",
            "avatar": avatar_url,
            "avatar_url": avatar_url,
            "city": city,
            "state": state,
            "country": country,
            "location": location_str,
            "status": emp_doc.get("status") or "Active",
            "is_primary_recruiter": bool(emp_doc.get("is_primary_recruiter")),
            "can_publish_jobs": bool(emp_doc.get("can_publish_jobs")),
            "can_hire": bool(emp_doc.get("can_hire")),
            "can_manage_recruiters": bool(emp_doc.get("can_manage_recruiters")),
        }

        company_data = {
            "company_id": company_doc.name if company_doc else company_id,
            "company_name": company_doc.get("company_name") if company_doc else company_id,
            "legal_name": company_doc.get("legal_name") if company_doc else "",
            "industry": company_doc.get("industry") if company_doc else "",
            "company_size": company_doc.get("company_size") if company_doc else "",
            "website": company_doc.get("website") if company_doc else "",
            "logo": logo_url,
            "description": company_doc.get("description") if company_doc else "",
            "email": company_doc.get("email") if company_doc else "",
            "phone": company_doc.get("phone") if company_doc else "",
            "address_line_1": company_doc.get("address_line_1") if company_doc else "",
            "address_line_2": company_doc.get("address_line_2") if company_doc else "",
            "city": company_doc.get("city") if company_doc else "",
            "state": company_doc.get("state") if company_doc else "",
            "country": company_doc.get("country") if company_doc else "",
            "postal_code": company_doc.get("postal_code") if company_doc else "",
        }

        contact_details = {
            "email": user_doc.email if user_doc else user_id,
            "phone": phone,
            "hr_email": company_doc.get("hr_email") if company_doc else "",
            "support_email": company_doc.get("support_email") if company_doc else "",
        }

        preferences = {
            "timezone": timezone,
            "language": language,
            "notification_preferences": notification_prefs or {},
        }

        return {
            "employer": employer_data,
            "company": company_data,
            "avatar_url": avatar_url,
            "role": emp_doc.get("role") or "Viewer",
            "designation": emp_doc.get("designation") or "",
            "contact_details": contact_details,
            "preferences": preferences,
        }

    # ------------------------------------------------------------------
    # Profile UPDATE
    # ------------------------------------------------------------------

    def update_profile(self, data: dict) -> dict:
        """Apply partial updates to the Employer Profile with persistence across database tables.
        
        Rules:
        - Only update changed fields present in payload.
        - Do not overwrite existing values with null/None.
        - Update Employer User and sync with linked Frappe User doc.
        """
        validated_data = self.validator.validate_update_profile(data)
        if not validated_data:
            return self.get_profile()

        emp_doc = self._get_active_employer_user_doc()
        user_id = emp_doc.user

        # Fields mapped to Employer User DocType
        emp_fields = [
            "first_name", "last_name", "phone", "designation",
            "department", "bio", "timezone", "language", "country",
            "state", "city", "notification_preferences"
        ]

        emp_updated = False
        for field in emp_fields:
            if field in validated_data and validated_data[field] is not None:
                val = validated_data[field]
                if field == "notification_preferences" and isinstance(val, (dict, list)):
                    val = frappe.as_json(val)
                setattr(emp_doc, field, val)
                emp_updated = True

        # Re-compute full_name if first_name or last_name changed
        if "first_name" in validated_data or "last_name" in validated_data:
            fname = emp_doc.get("first_name") or ""
            lname = emp_doc.get("last_name") or ""
            emp_doc.full_name = f"{fname} {lname}".strip()
            emp_updated = True

        if emp_updated:
            emp_doc.save(ignore_permissions=True)

        # Sync changes to Frappe User DocType
        if frappe.db.exists("User", user_id):
            user_doc = frappe.get_doc("User", user_id)
            user_updated = False

            if "first_name" in validated_data and validated_data["first_name"]:
                user_doc.first_name = validated_data["first_name"]
                user_updated = True
            if "last_name" in validated_data and validated_data["last_name"] is not None:
                user_doc.last_name = validated_data["last_name"]
                user_updated = True
            if "phone" in validated_data and validated_data["phone"]:
                user_doc.mobile_no = validated_data["phone"]
                user_doc.phone = validated_data["phone"]
                user_updated = True
            if "bio" in validated_data and validated_data["bio"] is not None:
                user_doc.bio = validated_data["bio"]
                user_updated = True
            if "timezone" in validated_data and validated_data["timezone"]:
                user_doc.time_zone = validated_data["timezone"]
                user_updated = True
            if "language" in validated_data and validated_data["language"]:
                user_doc.language = validated_data["language"]
                user_updated = True

            if user_updated:
                user_doc.save(ignore_permissions=True)

        # Notify asynchronous subscriber
        self._notify(
            title="Profile Updated",
            message=f"Employer profile for '{emp_doc.full_name or emp_doc.user}' was updated.",
            company=emp_doc.company,
            recipient=user_id,
            entity_id=emp_doc.name,
        )

        frappe.db.commit()
        return self.get_profile()

    # ------------------------------------------------------------------
    # Profile Photo UPLOAD
    # ------------------------------------------------------------------

    def upload_profile_photo(
        self,
        file_content: bytes,
        file_name: str,
        content_type: str | None = None,
    ) -> dict:
        """Upload profile photo, attach to Employer User via Frappe File DocType, and return absolute URLs."""
        if not file_content:
            raise ATSValidationError("Uploaded file is empty.", field="file")
        if len(file_content) > MAX_FILE_SIZE_BYTES:
            raise ATSValidationError("File size exceeds 5MB limit.", field="file")

        # Content-type / Extension validation
        if not content_type:
            content_type, _ = mimetypes.guess_type(file_name)
        content_type = content_type or "application/octet-stream"

        ext = "." + file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        if content_type not in ALLOWED_IMAGE_MIMES and ext not in ALLOWED_IMAGE_EXTENSIONS:
            raise ATSValidationError(
                f"Unsupported image type '{content_type}'. Allowed types: PNG, JPG, JPEG, WEBP.",
                field="file",
            )

        emp_doc = self._get_active_employer_user_doc()

        # Delete existing attached profile image file if exists
        existing_files = frappe.get_all(
            "File",
            filters={
                "attached_to_doctype": DOCTYPE_EMPLOYER_USER,
                "attached_to_name": emp_doc.name,
                "attached_to_field": "avatar",
            },
            fields=["name"],
        )
        for ef in existing_files:
            try:
                frappe.delete_doc("File", ef["name"], ignore_permissions=True)
            except Exception as exc:
                frappe.logger().warning(f"Could not delete old avatar file {ef['name']}: {exc}")

        # Create Frappe File document
        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": file_name,
            "attached_to_doctype": DOCTYPE_EMPLOYER_USER,
            "attached_to_name": emp_doc.name,
            "attached_to_field": "avatar",
            "content": file_content,
            "is_private": 0,
        })
        file_doc.insert(ignore_permissions=True)

        # Update Employer User avatar reference
        file_url = file_doc.file_url
        setattr(emp_doc, "avatar", file_url)
        emp_doc.save(ignore_permissions=True)

        # Update standard Frappe User user_image reference
        if frappe.db.exists("User", emp_doc.user):
            user_doc = frappe.get_doc("User", emp_doc.user)
            user_doc.user_image = file_url
            user_doc.save(ignore_permissions=True)

        frappe.db.commit()

        abs_file_url = self._get_absolute_url(file_url)

        return {
            "file_url": abs_file_url,
            "thumbnail": abs_file_url,
            "image_metadata": {
                "name": file_doc.name,
                "file_name": file_name,
                "file_size": len(file_content),
                "mime_type": content_type,
            },
        }

    # ------------------------------------------------------------------
    # Profile Photo REMOVE
    # ------------------------------------------------------------------

    def remove_profile_photo(self) -> dict:
        """Delete avatar attachment, clear references on Employer User and User, and return updated state."""
        emp_doc = self._get_active_employer_user_doc()

        # Find and delete File records attached to Employer User avatar
        existing_files = frappe.get_all(
            "File",
            filters={
                "attached_to_doctype": DOCTYPE_EMPLOYER_USER,
                "attached_to_name": emp_doc.name,
            },
            fields=["name", "file_url"],
        )
        for ef in existing_files:
            if ef.get("file_url") == getattr(emp_doc, "avatar", None) or ef.get("name"):
                try:
                    frappe.delete_doc("File", ef["name"], ignore_permissions=True)
                except Exception as exc:
                    frappe.logger().warning(f"Could not delete avatar file {ef['name']}: {exc}")

        # Clear references
        setattr(emp_doc, "avatar", None)
        emp_doc.save(ignore_permissions=True)

        if frappe.db.exists("User", emp_doc.user):
            user_doc = frappe.get_doc("User", emp_doc.user)
            user_doc.user_image = None
            user_doc.save(ignore_permissions=True)

        frappe.db.commit()

        return {
            "file_url": None,
            "avatar": None,
            "message": "Profile photo removed successfully.",
        }
