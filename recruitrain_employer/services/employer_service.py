# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.services.employer_service
================================================

Employer User & Team Management Business Logic Service.

Owns all business logic related to:
- Employer User record retrieval, listing, and updates
- Team member invitation workflow
- Role management
- User deactivation
"""

from __future__ import annotations

import frappe

from recruitrain_employer.utils.constants import (
    DOCTYPE_EMPLOYER_USER,
    DOCTYPE_COMPANY,
)
from recruitrain_employer.utils.exceptions import (
    ATSAuthenticationError,
    ATSNotFoundError,
    ATSPermissionError,
    ATSValidationError,
)
from recruitrain_employer.utils.login_audit import get_employer_user_for_user


class EmployerService:
    """Encapsulates business logic for Employer User and team management."""

    # ------------------------------------------------------------------
    # Notification Helper
    # ------------------------------------------------------------------

    @staticmethod
    def _notify(title: str, message: str, priority: str, category: str, company: str, recipient: str, entity_id: str | None = None) -> None:
        try:
            from recruitrain_employer.services.notification_service import NotificationService
            from recruitrain_employer.utils.permissions import get_current_company
            ns = NotificationService()
            target_company = company or get_current_company()
            ns.create_notification(
                raw_data={
                    "title": title,
                    "message": message,
                    "notification_type": category,
                    "priority": priority,
                    "category": category,
                    "entity_type": "Employer User",
                    "entity_id": entity_id or recipient,
                    "action_url": "/team",
                    "action_label": "View Team",
                },
                company=target_company,
                recipient=recipient or getattr(frappe.session, "user", "Administrator"),
                created_by=getattr(frappe.session, "user", "System"),
            )
        except Exception as exc:
            frappe.logger().error(f"Employer notification error: {exc}")

    # ------------------------------------------------------------------
    # Employer User CRUD
    # ------------------------------------------------------------------

    def get_employer_user(self, employer_user_id: str) -> dict:
        """Retrieve a single Employer User record by ID."""
        if not employer_user_id:
            raise ATSValidationError("employer_user_id is required.", field="employer_user_id")

        if not frappe.db.exists(DOCTYPE_EMPLOYER_USER, employer_user_id):
            raise ATSNotFoundError(
                f"Employer User '{employer_user_id}' was not found.",
                doctype=DOCTYPE_EMPLOYER_USER,
                name=employer_user_id,
            )

        doc = frappe.get_doc(DOCTYPE_EMPLOYER_USER, employer_user_id)
        return doc.as_dict()

    def get_last_login(self, user: str | None = None) -> dict:
        """Retrieve last login audit details for an Employer User.

        Parameters
        ----------
        user : str | None, optional
            Frappe user ID / email. Defaults to currently authenticated session user.

        Returns
        -------
        dict
            Dict containing last login timestamp, IP, User-Agent, and login count.
        """
        user_id = user or getattr(frappe.session, "user", None) or "Guest"

        if user_id == "Guest":
            raise ATSAuthenticationError("Authentication required. Please log in.")

        emp_user_name = get_employer_user_for_user(user_id)
        if not emp_user_name:
            if user_id == "Administrator":
                return {
                    "user": "Administrator",
                    "last_login_at": None,
                    "last_login_ip": None,
                    "last_login_user_agent": None,
                    "login_count": 0,
                }
            raise ATSNotFoundError(
                f"Employer User mapping for '{user_id}' was not found.",
                doctype=DOCTYPE_EMPLOYER_USER,
                name=user_id,
            )

        doc = frappe.get_doc(DOCTYPE_EMPLOYER_USER, emp_user_name)
        return doc.get_last_login()


    def list_employer_users(self, filters: dict | None = None, pagination: dict | None = None) -> dict:
        """Return a paginated list of Employer Users for the current company."""
        filters = filters or {}
        pagination = pagination or {}
        page = pagination.get("page", 1)
        page_size = pagination.get("page_size", 20)

        query_filters = {}
        if filters.get("role"):
            query_filters["role"] = filters["role"]
        if filters.get("status"):
            query_filters["status"] = filters["status"]
        if filters.get("company"):
            query_filters["company"] = filters["company"]

        start = (page - 1) * page_size
        records = frappe.get_all(
            DOCTYPE_EMPLOYER_USER,
            filters=query_filters,
            fields=["name", "user", "user_name", "email", "role", "company", "status", "creation"],
            start=start,
            page_length=page_size,
            order_by="creation desc",
        )
        total = frappe.db.count(DOCTYPE_EMPLOYER_USER, filters=query_filters)

        return {
            "data": records,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def update_employer_user(self, employer_user_id: str, data: dict) -> dict:
        """Update mutable fields on an existing Employer User record."""
        if not employer_user_id:
            raise ATSValidationError("employer_user_id is required.")

        doc = frappe.get_doc(DOCTYPE_EMPLOYER_USER, employer_user_id)
        updatable = ["first_name", "last_name", "user_name", "phone", "role", "status"]
        
        for k in updatable:
            if k in data:
                setattr(doc, k, data[k])

        doc.save(ignore_permissions=True)

        company = getattr(doc, "company", None)
        recipient = getattr(doc, "user", None) or doc.get("email")
        self._notify(
            title="Employer Profile Updated",
            message=f"Employer user account {doc.name} was updated.",
            priority="Low",
            category="System",
            company=company,
            recipient=recipient,
            entity_id=doc.name,
        )

        return doc.as_dict()

    # ------------------------------------------------------------------
    # Team Management
    # ------------------------------------------------------------------

    def invite_team_member(self, email: str, role: str, company: str) -> dict:
        """Invite a new team member by email."""
        if not email:
            raise ATSValidationError("email is required.", field="email")
        if not role:
            raise ATSValidationError("role is required.", field="role")

        existing = frappe.db.exists(DOCTYPE_EMPLOYER_USER, {"email": email, "company": company})
        if existing:
            raise ATSValidationError(f"Employer user with email '{email}' already exists in this company.")

        doc = frappe.new_doc(DOCTYPE_EMPLOYER_USER)
        doc.email = email
        doc.user = email
        doc.role = role
        doc.company = company
        doc.status = "Active"
        doc.insert(ignore_permissions=True)

        self._notify(
            title="Employer Invited",
            message=f"New team member {email} invited as '{role}'.",
            priority="High",
            category="System",
            company=company,
            recipient=email,
            entity_id=doc.name,
        )

        return doc.as_dict()

    def deactivate_employer_user(self, employer_user_id: str) -> dict:
        """Deactivate an Employer User, revoking system access."""
        doc = frappe.get_doc(DOCTYPE_EMPLOYER_USER, employer_user_id)
        doc.status = "Inactive"
        doc.save(ignore_permissions=True)

        company = getattr(doc, "company", None)
        recipient = getattr(doc, "user", doc.email)
        self._notify(
            title="Employer Deactivated",
            message=f"Employer user account {doc.name} ({doc.email}) was deactivated.",
            priority="High",
            category="System",
            company=company,
            recipient=recipient,
            entity_id=doc.name,
        )

        return doc.as_dict()

    def update_employer_role(self, employer_user_id: str, role: str) -> dict:
        """Change the role of an Employer User within the company."""
        if not role:
            raise ATSValidationError("role is required.", field="role")

        doc = frappe.get_doc(DOCTYPE_EMPLOYER_USER, employer_user_id)
        old_role = doc.role
        doc.role = role
        doc.save(ignore_permissions=True)

        company = getattr(doc, "company", None)
        recipient = getattr(doc, "user", doc.email)
        self._notify(
            title="Employer Role Changed",
            message=f"Role for {doc.email} changed from '{old_role}' to '{role}'.",
            priority="Medium",
            category="System",
            company=company,
            recipient=recipient,
            entity_id=doc.name,
        )

        return doc.as_dict()
