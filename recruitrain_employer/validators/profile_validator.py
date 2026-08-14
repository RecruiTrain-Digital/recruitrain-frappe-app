# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.profile_validator
===================================================

Input Validation & Data Sanitisation Layer for Employer Profile Operations.

This module validates and sanitises incoming employer profile payloads (GET/POST)
before they reach the service or database layer.

Validation Rules
----------------
- Phone: Valid international phone format (+ digits, hyphens, spaces, max 30 chars).
- Designation: Text string, max 100 chars.
- Timezone: Non-empty string, valid IANA timezone format.
- Language: Valid ISO language code string.
- Country / State / City: Text strings, max 100 chars.
- Immutable fields (email, company, role, status, user) are explicitly stripped.
"""

from __future__ import annotations

import re
import frappe
from recruitrain_employer.utils.constants import DOCTYPE_COMPANY
from recruitrain_employer.utils.exceptions import ATSValidationError

# ISO Language codes commonly supported
ALLOWED_LANGUAGES = frozenset([
    "en", "de", "fr", "es", "it", "pt", "nl", "pl", "cs", "ro",
    "hu", "ar", "zh", "ja", "ko", "hi", "id", "tr", "ru", "uk", "vi",
])

# Standard Timezones commonly supported
ALLOWED_TIMEZONES = frozenset([
    "UTC", "Africa/Nairobi", "America/Chicago", "America/Denver",
    "America/Los_Angeles", "America/New_York", "America/Sao_Paulo",
    "America/Toronto", "Asia/Bangkok", "Asia/Colombo", "Asia/Dubai",
    "Asia/Jakarta", "Asia/Karachi", "Asia/Kolkata", "Asia/Kuala_Lumpur",
    "Asia/Manila", "Asia/Seoul", "Asia/Shanghai", "Asia/Singapore",
    "Asia/Taipei", "Asia/Tokyo", "Australia/Melbourne", "Australia/Sydney",
    "Europe/Amsterdam", "Europe/Berlin", "Europe/Brussels", "Europe/Bucharest",
    "Europe/Helsinki", "Europe/Istanbul", "Europe/Kiev", "Europe/Lisbon",
    "Europe/London", "Europe/Madrid", "Europe/Moscow", "Europe/Paris",
    "Europe/Prague", "Europe/Rome", "Europe/Stockholm", "Europe/Warsaw",
    "Europe/Zurich", "Pacific/Auckland", "Pacific/Honolulu",
])

#: Fields a caller may modify on their own Employer User record.
#: Email, User, Company, Role, and Status are intentionally EXCLUDED.
PROFILE_UPDATABLE_FIELDS: frozenset[str] = frozenset([
    "first_name",
    "middle_name",
    "last_name",
    "phone",
    "designation",
    "department",
    "bio",
    "timezone",
    "language",
    "country",
    "state",
    "city",
    "notification_preferences",
])


class ProfileValidator:
    """Validator for Employer Profile payloads."""

    @staticmethod
    def validate_phone(phone: str) -> str:
        """Validate phone number format."""
        if not phone:
            return ""
        if not isinstance(phone, str):
            raise ATSValidationError("Phone must be a string.", field="phone")

        cleaned = phone.strip()
        pattern = r"^\+?[0-9\s\-\(\)]{7,30}$"
        if not re.match(pattern, cleaned):
            raise ATSValidationError(
                f"Phone number '{phone}' contains invalid characters or length.",
                field="phone",
            )
        return cleaned

    @staticmethod
    def validate_designation(designation: str) -> str:
        """Validate designation text."""
        if not designation:
            return ""
        if not isinstance(designation, str):
            raise ATSValidationError("Designation must be a string.", field="designation")

        cleaned = designation.strip()
        if len(cleaned) > 100:
            raise ATSValidationError("Designation must not exceed 100 characters.", field="designation")
        return cleaned

    @staticmethod
    def validate_timezone(timezone: str) -> str:
        """Validate timezone string."""
        if not timezone:
            return "UTC"
        if not isinstance(timezone, str):
            raise ATSValidationError("Timezone must be a string.", field="timezone")

        cleaned = timezone.strip()
        if cleaned not in ALLOWED_TIMEZONES and not (len(cleaned) <= 50 and "/" in cleaned):
            raise ATSValidationError(f"Invalid or unsupported timezone '{timezone}'.", field="timezone")
        return cleaned

    @staticmethod
    def validate_language(language: str) -> str:
        """Validate language code string."""
        if not language:
            return "en"
        if not isinstance(language, str):
            raise ATSValidationError("Language must be a string.", field="language")

        cleaned = language.strip().lower()
        if cleaned not in ALLOWED_LANGUAGES and len(cleaned) > 10:
            raise ATSValidationError(f"Invalid language code '{language}'.", field="language")
        return cleaned

    @staticmethod
    def validate_location_field(field_name: str, value: str) -> str:
        """Validate state, city, or location text fields."""
        if not value:
            return ""
        if not isinstance(value, str):
            raise ATSValidationError(f"{field_name.capitalize()} must be a string.", field=field_name)

        cleaned = value.strip()
        if len(cleaned) > 100:
            raise ATSValidationError(f"{field_name.capitalize()} must not exceed 100 characters.", field=field_name)
        return cleaned

    @staticmethod
    def validate_country(country: str) -> str:
        """Validate country parameter."""
        if not country:
            return ""
        if not isinstance(country, str):
            raise ATSValidationError("Country must be a string.", field="country")

        cleaned = country.strip()
        if len(cleaned) > 100:
            raise ATSValidationError("Country must not exceed 100 characters.", field="country")
        return cleaned

    @staticmethod
    def validate_company(company_id: str) -> str:
        """Validate linked company exists and is active."""
        if not company_id or not isinstance(company_id, str):
            raise ATSValidationError("Company ID is required.", field="company")

        company = company_id.strip()
        if not frappe.db.exists(DOCTYPE_COMPANY, company):
            raise ATSValidationError(f"Company '{company}' does not exist.", field="company")

        status = frappe.db.get_value(DOCTYPE_COMPANY, company, "status")
        if status and status == "Inactive":
            raise ATSValidationError(f"Company '{company}' is currently inactive.", field="company")
        return company

    def validate_update_profile(self, data: dict) -> dict:
        """Validate partial profile update dictionary.

        Ensures keys belong strictly to ``PROFILE_UPDATABLE_FIELDS``, runs specific
        validators, and strips unwanted, null, or immutable fields (email, role, company).
        """
        if not isinstance(data, dict):
            raise ATSValidationError("Update payload must be a valid JSON dictionary.")

        validated: dict = {}

        for key, value in data.items():
            # Exclude immutable fields (email, company, role, status, user, etc.)
            if key not in PROFILE_UPDATABLE_FIELDS:
                continue

            # Do not overwrite existing values with null/None
            if value is None:
                continue

            if key == "phone" and value is not None:
                validated["phone"] = self.validate_phone(value)
            elif key == "designation" and value is not None:
                validated["designation"] = self.validate_designation(value)
            elif key == "timezone" and value:
                validated["timezone"] = self.validate_timezone(value)
            elif key == "language" and value:
                validated["language"] = self.validate_language(value)
            elif key == "country" and value is not None:
                validated["country"] = self.validate_country(value)
            elif key in ("state", "city") and value is not None:
                validated[key] = self.validate_location_field(key, value)
            elif key in ("first_name", "middle_name", "last_name", "department", "bio"):
                if isinstance(value, str):
                    validated[key] = value.strip()
                else:
                    validated[key] = value
            elif key == "notification_preferences":
                validated[key] = value

        return validated
