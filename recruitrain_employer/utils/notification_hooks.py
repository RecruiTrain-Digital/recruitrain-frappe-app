# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.utils.notification_hooks
================================================

Automatic Notification Generation Hooks for Real Recruitment Events.

Hooks into standard Frappe DocType document lifecycle events (after_insert, on_update)
to trigger persistent company-scoped and recipient-scoped Notifications via NotificationService.
"""

from __future__ import annotations

import frappe
from recruitrain_employer.services.notification_service import NotificationService


# ------------------------------------------------------------------
# Helper Functions
# ------------------------------------------------------------------

def resolve_company(doc) -> str | None:
    """Extract or resolve valid active company for a document."""
    comp = getattr(doc, "company", None)
    if comp:
        return comp

    # Try linked documents
    for field, doctype in [
        ("job_application", "Job Application"),
        ("job_opening", "Job Opening"),
        ("candidate", "Candidate"),
    ]:
        val = getattr(doc, field, None)
        if val and frappe.db.exists(doctype, val):
            linked_comp = frappe.db.get_value(doctype, val, "company")
            if linked_comp:
                return linked_comp

    # Fallback to current authenticated employer user company
    session_user = getattr(frappe.session, "user", None)
    if session_user and session_user != "Guest":
        return frappe.db.get_value("Employer User", {"user": session_user, "status": "Active"}, "company")

    return None


def resolve_recipients(doc, company: str) -> list[str]:
    """Resolve all active Employer User recipients for a given company and document."""
    recipients = set()

    # Explicit user fields on document
    for field in ("interviewer", "recruiter", "hiring_manager", "assigned_recruiter", "owner"):
        val = getattr(doc, field, None)
        if val and val != "Guest" and frappe.db.exists("User", val):
            recipients.add(val)

    # Active session user if authenticated
    session_user = getattr(frappe.session, "user", None)
    if session_user and session_user != "Guest":
        recipients.add(session_user)

    # Active employer users in this company
    if company:
        emp_users = frappe.get_all(
            "Employer User",
            filters={"company": company, "status": "Active"},
            pluck="user",
        )
        for u in emp_users:
            if u and u != "Guest":
                recipients.add(u)

    if not recipients:
        recipients.add(getattr(frappe.session, "user", "Administrator"))

    return list(recipients)


def resolve_candidate_display(candidate_id: str | None) -> str:
    """Resolve human-readable candidate name."""
    if not candidate_id:
        return "Candidate"
    if frappe.db.exists("Candidate", candidate_id):
        cand_data = frappe.db.get_value(
            "Candidate",
            candidate_id,
            ["first_name", "last_name", "candidate_name"],
            as_dict=True,
        )
        if cand_data:
            full = f"{cand_data.get('first_name') or ''} {cand_data.get('last_name') or ''}".strip()
            if full:
                return full
            if cand_data.get("candidate_name"):
                return cand_data.get("candidate_name")
    return str(candidate_id)


def resolve_job_display(job_id: str | None) -> str:
    """Resolve human-readable job title."""
    if not job_id:
        return "Job Position"
    if frappe.db.exists("Job Opening", job_id):
        title = frappe.db.get_value("Job Opening", job_id, "job_title")
        if title:
            return title
    return str(job_id)


def is_notification_enabled_for_recipient(
    recipient: str,
    company: str,
    notification_type: str,
    category: str = "",
) -> bool:
    """Check if notification delivery is enabled for recipient according to preferences."""
    try:
        service = NotificationService()
        prefs = service.get_notification_preferences(recipient, company)
        if not prefs:
            return True

        if prefs.get("in_app_notifications") is False:
            return False

        nt_key = str(notification_type or "").lower()
        cat_key = str(category or "").lower()

        if prefs.get(nt_key) is False or prefs.get(cat_key) is False:
            return False

        if nt_key == "interview" and (prefs.get("interview_reminders") is False or prefs.get("interview") is False):
            return False
        if nt_key == "application" and (prefs.get("application_updates") is False or prefs.get("application") is False):
            return False
        if nt_key == "offer" and (prefs.get("offer_alerts") is False or prefs.get("offer") is False):
            return False
        if nt_key == "job" and (prefs.get("job_updates") is False or prefs.get("job") is False):
            return False
        if nt_key == "candidate" and (prefs.get("candidate_updates") is False or prefs.get("candidate") is False):
            return False
        if nt_key == "system" and (prefs.get("system_alerts") is False or prefs.get("system") is False):
            return False

        return True
    except Exception:
        return True


def notify_event(
    doc,
    title: str,
    message: str,
    notification_type: str,
    priority: str,
    entity_type: str,
    entity_id: str,
    action_url: str,
    category: str = "recruitment",
):
    """Centralized notification dispatcher with duplicate prevention and transaction safety."""
    company = resolve_company(doc)
    if not company:
        frappe.logger("notification_hooks").warning(f"resolve_company returned None for {entity_type} {entity_id}")
        return

    recipients = resolve_recipients(doc, company)
    service = NotificationService()

    meta = frappe.get_meta("Notification Log")
    recipient_field = "recipient" if meta.has_field("recipient") else "for_user"
    doc_type_field = "entity_type" if meta.has_field("entity_type") else "document_type"
    doc_id_field = "entity_id" if meta.has_field("entity_id") else "document_name"
    subj_field = "title" if meta.has_field("title") else "subject"

    for recipient in recipients:
        # Preference check: suppress if recipient explicitly turned OFF this category or channel
        if not is_notification_enabled_for_recipient(recipient, company, notification_type, category):
            continue

        filters = {
            recipient_field: recipient,
            doc_type_field: entity_type,
            doc_id_field: str(entity_id),
            subj_field: title,
        }
        if meta.has_field("company") and company:
            filters["company"] = company

        # Idempotency check: prevent duplicate notification for same document event
        if frappe.db.exists("Notification Log", filters):
            continue

        try:
            service.create_notification(
                raw_data={
                    "title": title,
                    "message": message,
                    "priority": priority,
                    "notification_type": notification_type,
                    "category": category,
                    "entity_type": entity_type,
                    "entity_id": str(entity_id),
                    "action_url": action_url,
                    "action_label": title,
                },
                company=company,
                recipient=recipient,
                created_by=getattr(frappe.session, "user", "Administrator"),
            )
        except Exception as exc:
            frappe.logger().error(f"Failed to dispatch event notification for {entity_type} {entity_id}: {str(exc)}")


# ------------------------------------------------------------------
# Interview Document Event Hooks
# ------------------------------------------------------------------

def on_interview_after_insert(doc, method=None):
    """Trigger notification when a new Interview is created."""
    cand_name = resolve_candidate_display(doc.candidate)
    job_title = resolve_job_display(doc.job_opening)
    notify_event(
        doc,
        title="Interview scheduled",
        message=f"An interview has been scheduled for {cand_name} for {job_title}.",
        notification_type="Interview",
        priority="Medium",
        entity_type="Interview",
        entity_id=doc.name,
        action_url=f"/app/interviews?id={doc.name}",
    )


def on_interview_on_update(doc, method=None):
    """Trigger notification on Interview rescheduling or cancellation."""
    if getattr(doc.flags, "in_insert", False) or not doc.get_doc_before_save():
        return

    old_doc = doc.get_doc_before_save()
    cand_name = resolve_candidate_display(doc.candidate)
    job_title = resolve_job_display(doc.job_opening)

    if doc.has_value_changed("status") and doc.status == "Cancelled":
        notify_event(
            doc,
            title="Interview cancelled",
            message=f"Interview for {cand_name} for {job_title} has been cancelled.",
            notification_type="Interview",
            priority="High",
            entity_type="Interview",
            entity_id=doc.name,
            action_url=f"/app/interviews?id={doc.name}",
        )
    elif doc.has_value_changed("scheduled_on") or (doc.has_value_changed("status") and doc.status == "Rescheduled"):
        sched_time = doc.scheduled_on or "new date"
        notify_event(
            doc,
            title="Interview rescheduled",
            message=f"Interview for {cand_name} for {job_title} has been rescheduled to {sched_time}.",
            notification_type="Interview",
            priority="High",
            entity_type="Interview",
            entity_id=doc.name,
            action_url=f"/app/interviews?id={doc.name}",
        )


# ------------------------------------------------------------------
# Job Opening Document Event Hooks
# ------------------------------------------------------------------

def on_job_opening_after_insert(doc, method=None):
    """Trigger notification when a new Job Opening is created."""
    job_title = doc.job_title or doc.name
    notify_event(
        doc,
        title="Job opening created",
        message=f"Job opening '{job_title}' has been created.",
        notification_type="Job",
        priority="Medium",
        entity_type="Job Opening",
        entity_id=doc.name,
        action_url=f"/app/jobs?id={doc.name}",
    )


def on_job_opening_on_update(doc, method=None):
    """Trigger notification when Job Opening status changes to Open or Published."""
    if getattr(doc.flags, "in_insert", False) or not doc.get_doc_before_save():
        return

    if doc.has_value_changed("status") and doc.status in ("Open", "Published"):
        job_title = doc.job_title or doc.name
        notify_event(
            doc,
            title="Job opening published",
            message=f"Job opening '{job_title}' status changed to {doc.status}.",
            notification_type="Job",
            priority="Medium",
            entity_type="Job Opening",
            entity_id=doc.name,
            action_url=f"/app/jobs?id={doc.name}",
        )


# ------------------------------------------------------------------
# Job Application Document Event Hooks
# ------------------------------------------------------------------

def on_job_application_after_insert(doc, method=None):
    """Trigger notification when a new Job Application is created."""
    cand_name = resolve_candidate_display(doc.candidate)
    job_title = resolve_job_display(doc.job_opening)
    notify_event(
        doc,
        title="New application received",
        message=f"A new application has been received for {job_title} from {cand_name}.",
        notification_type="Application",
        priority="Medium",
        entity_type="Job Application",
        entity_id=doc.name,
        action_url=f"/app/applications?id={doc.name}",
    )


def on_job_application_on_update(doc, method=None):
    """Trigger notification when Job Application stage or status changes."""
    if getattr(doc.flags, "in_insert", False) or not doc.get_doc_before_save():
        return

    if doc.has_value_changed("current_stage") or doc.has_value_changed("status"):
        cand_name = resolve_candidate_display(doc.candidate)
        new_stage = doc.current_stage or doc.status
        notify_event(
            doc,
            title="Application stage updated",
            message=f"Application for {cand_name} moved to stage {new_stage}.",
            notification_type="Application",
            priority="Medium",
            entity_type="Job Application",
            entity_id=doc.name,
            action_url=f"/app/applications?id={doc.name}",
        )


# ------------------------------------------------------------------
# Candidate Document Event Hooks
# ------------------------------------------------------------------

def on_candidate_on_update(doc, method=None):
    """Trigger notification when Candidate status changes."""
    if getattr(doc.flags, "in_insert", False) or not doc.get_doc_before_save():
        return

    if doc.has_value_changed("status"):
        cand_name = resolve_candidate_display(doc.name)
        notify_event(
            doc,
            title="Candidate status updated",
            message=f"Candidate {cand_name} status updated to {doc.status}.",
            notification_type="Candidate",
            priority="Medium",
            entity_type="Candidate",
            entity_id=doc.name,
            action_url=f"/app/candidates?id={doc.name}",
        )


# ------------------------------------------------------------------
# Offer Document Event Hooks
# ------------------------------------------------------------------

def on_offer_after_insert(doc, method=None):
    """Trigger notification when a new Offer is created."""
    cand_name = resolve_candidate_display(doc.candidate)
    job_title = resolve_job_display(doc.job_opening)
    notify_event(
        doc,
        title="Offer created",
        message=f"Offer letter created for {cand_name} for position {job_title}.",
        notification_type="Offer",
        priority="High",
        entity_type="Offer",
        entity_id=doc.name,
        action_url=f"/app/offers?id={doc.name}",
    )


def on_offer_on_update(doc, method=None):
    """Trigger notification when Offer status changes."""
    if getattr(doc.flags, "in_insert", False) or not doc.get_doc_before_save():
        return

    if doc.has_value_changed("offer_status") or doc.has_value_changed("status"):
        cand_name = resolve_candidate_display(doc.candidate)
        new_status = getattr(doc, "offer_status", None) or getattr(doc, "status", None)
        notify_event(
            doc,
            title="Offer status updated",
            message=f"Offer status for {cand_name} updated to {new_status}.",
            notification_type="Offer",
            priority="High",
            entity_type="Offer",
            entity_id=doc.name,
            action_url=f"/app/offers?id={doc.name}",
        )
