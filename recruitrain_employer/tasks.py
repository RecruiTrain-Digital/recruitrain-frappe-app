# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.tasks
==========================

Scheduled background tasks for automated reminder notifications.
Enforces scheduled backend-only generation for system events (interviews,
offers, document expirations, job expirations, joining dates).
"""

from __future__ import annotations

import datetime
import frappe
from frappe.utils import add_days, add_to_date, now_datetime, nowdate

from recruitrain_employer.services.notification_service import NotificationService


def send_daily_reminders() -> None:
    """Daily scheduled background task to process system reminders."""
    send_interview_tomorrow_reminders()
    send_offer_expiry_reminders()
    send_document_and_passport_reminders()
    send_job_expiry_reminders()
    send_candidate_joining_reminders()


def send_hourly_reminders() -> None:
    """Hourly scheduled background task for time-sensitive notifications."""
    send_interview_30min_reminders()
    send_pending_document_verification_reminders()


def send_short_term_reminders() -> None:
    """Periodic task executed on all scheduler cycles for high-urgency triggers."""
    send_interview_30min_reminders()


def send_interview_tomorrow_reminders() -> None:
    """Send reminder notifications for interviews scheduled for tomorrow."""
    try:
        tomorrow = add_days(nowdate(), 1)
        interviews = frappe.get_all(
            "Interview",
            filters={
                "scheduled_on": ["between", [f"{tomorrow} 00:00:00", f"{tomorrow} 23:59:59"]],
                "docstatus": 0,
            },
            fields=["name", "company", "candidate", "interviewer", "scheduled_on", "interview_type"],
        )
        svc = NotificationService()
        for item in interviews:
            recipient = item.get("interviewer") or "Administrator"
            svc.create_notification(
                raw_data={
                    "title": "Interview Starts Tomorrow",
                    "message": f"Interview {item['name']} ({item.get('interview_type', 'Interview')}) is scheduled for tomorrow at {item.get('scheduled_on')}.",
                    "notification_type": "Reminder",
                    "priority": "High",
                    "category": "Interview",
                    "entity_type": "Interview",
                    "entity_id": item["name"],
                    "action_url": f"/interviews/{item['name']}",
                    "action_label": "View Interview",
                },
                company=item.get("company"),
                recipient=recipient,
            )
    except Exception as exc:
        frappe.logger().error(f"Error in send_interview_tomorrow_reminders: {exc}")


def send_interview_30min_reminders() -> None:
    """Send urgent reminder for interviews scheduled in ~30 minutes."""
    try:
        now = now_datetime()
        window_start = add_to_date(now, minutes=25)
        window_end = add_to_date(now, minutes=35)
        interviews = frappe.get_all(
            "Interview",
            filters={
                "scheduled_on": ["between", [str(window_start), str(window_end)]],
                "docstatus": 0,
            },
            fields=["name", "company", "interviewer", "scheduled_on", "interview_type"],
        )
        svc = NotificationService()
        for item in interviews:
            recipient = item.get("interviewer") or "Administrator"
            svc.create_notification(
                raw_data={
                    "title": "Interview Starts in 30 Minutes",
                    "message": f"Reminder: Interview {item['name']} starts in 30 minutes ({item.get('scheduled_on')}).",
                    "notification_type": "Reminder",
                    "priority": "Urgent",
                    "category": "Interview",
                    "entity_type": "Interview",
                    "entity_id": item["name"],
                    "action_url": f"/interviews/{item['name']}",
                    "action_label": "Join / View Interview",
                },
                company=item.get("company"),
                recipient=recipient,
            )
    except Exception as exc:
        frappe.logger().error(f"Error in send_interview_30min_reminders: {exc}")


def send_offer_expiry_reminders() -> None:
    """Send reminder for offers expiring tomorrow."""
    try:
        tomorrow = add_days(nowdate(), 1)
        if not frappe.db.has_column("Offer", "offer_expiry_date"):
            return
        offers = frappe.get_all(
            "Offer",
            filters={
                "offer_expiry_date": tomorrow,
                "status": ["in", ["Sent", "Draft"]],
            },
            fields=["name", "company", "candidate", "job_application"],
        )
        svc = NotificationService()
        for item in offers:
            svc.create_notification(
                raw_data={
                    "title": "Offer Expires Tomorrow",
                    "message": f"Offer {item['name']} for candidate {item.get('candidate')} will expire tomorrow.",
                    "notification_type": "Reminder",
                    "priority": "High",
                    "category": "Offer",
                    "entity_type": "Offer",
                    "entity_id": item["name"],
                    "action_url": f"/offers/{item['name']}",
                    "action_label": "View Offer",
                },
                company=item.get("company"),
                recipient=getattr(frappe.session, "user", "Administrator"),
            )
    except Exception as exc:
        frappe.logger().error(f"Error in send_offer_expiry_reminders: {exc}")


def send_document_and_passport_reminders() -> None:
    """Send reminders for passport/visa expiring in 30 days."""
    try:
        target_date = add_days(nowdate(), 30)
        svc = NotificationService()
        if frappe.db.has_column("Candidate", "passport_expiry"):
            cands = frappe.get_all(
                "Candidate",
                filters={"passport_expiry": target_date},
                fields=["name", "candidate_name", "company"],
            )
            for c in cands:
                svc.create_notification(
                    raw_data={
                        "title": "Passport Expires in 30 Days",
                        "message": f"Passport for candidate {c.get('candidate_name', c['name'])} expires on {target_date}.",
                        "notification_type": "Reminder",
                        "priority": "High",
                        "category": "Candidate",
                        "entity_type": "Candidate",
                        "entity_id": c["name"],
                        "action_url": f"/candidates/{c['name']}",
                        "action_label": "View Candidate Profile",
                    },
                    company=c.get("company"),
                    recipient=getattr(frappe.session, "user", "Administrator"),
                )

        if frappe.db.has_column("Candidate", "visa_expiry"):
            cands = frappe.get_all(
                "Candidate",
                filters={"visa_expiry": target_date},
                fields=["name", "candidate_name", "company"],
            )
            for c in cands:
                svc.create_notification(
                    raw_data={
                        "title": "Visa Expires in 30 Days",
                        "message": f"Visa for candidate {c.get('candidate_name', c['name'])} expires on {target_date}.",
                        "notification_type": "Reminder",
                        "priority": "High",
                        "category": "Candidate",
                        "entity_type": "Candidate",
                        "entity_id": c["name"],
                        "action_url": f"/candidates/{c['name']}",
                        "action_label": "View Candidate Profile",
                    },
                    company=c.get("company"),
                    recipient=getattr(frappe.session, "user", "Administrator"),
                )
    except Exception as exc:
        frappe.logger().error(f"Error in send_document_and_passport_reminders: {exc}")


def send_job_expiry_reminders() -> None:
    """Send reminder for job openings expiring tomorrow."""
    try:
        tomorrow = add_days(nowdate(), 1)
        jobs = frappe.get_all(
            "Job Opening",
            filters={
                "closing_date": tomorrow,
                "status": "Open",
            },
            fields=["name", "job_title", "company"],
        )
        svc = NotificationService()
        for j in jobs:
            svc.create_notification(
                raw_data={
                    "title": "Job Opening Expires Tomorrow",
                    "message": f"Job opening '{j.get('job_title', j['name'])}' is scheduled to close tomorrow.",
                    "notification_type": "Reminder",
                    "priority": "Medium",
                    "category": "Job",
                    "entity_type": "Job Opening",
                    "entity_id": j["name"],
                    "action_url": f"/jobs/{j['name']}",
                    "action_label": "View Job",
                },
                company=j.get("company"),
                recipient=getattr(frappe.session, "user", "Administrator"),
            )
    except Exception as exc:
        frappe.logger().error(f"Error in send_job_expiry_reminders: {exc}")


def send_candidate_joining_reminders() -> None:
    """Send reminder for candidates joining tomorrow."""
    try:
        tomorrow = add_days(nowdate(), 1)
        svc = NotificationService()
        if frappe.db.has_column("Job Application", "target_joining_date"):
            apps = frappe.get_all(
                "Job Application",
                filters={
                    "target_joining_date": tomorrow,
                    "status": "Hired",
                },
                fields=["name", "candidate", "job_opening", "company"],
            )
            for a in apps:
                svc.create_notification(
                    raw_data={
                        "title": "Candidate Joining Tomorrow",
                        "message": f"Candidate for application {a['name']} is scheduled to join tomorrow.",
                        "notification_type": "Reminder",
                        "priority": "High",
                        "category": "Candidate",
                        "entity_type": "Job Application",
                        "entity_id": a["name"],
                        "action_url": f"/applications/{a['name']}",
                        "action_label": "View Application",
                    },
                    company=a.get("company"),
                    recipient=getattr(frappe.session, "user", "Administrator"),
                )
    except Exception as exc:
        frappe.logger().error(f"Error in send_candidate_joining_reminders: {exc}")


def send_pending_document_verification_reminders() -> None:
    """Send reminder for pending document verification."""
    try:
        if frappe.db.exists("DocType", "Candidate Document"):
            pending_docs = frappe.get_all(
                "Candidate Document",
                filters={"verification_status": "Pending"},
                fields=["name", "parent", "document_type"],
                limit=20,
            )
            svc = NotificationService()
            for d in pending_docs:
                svc.create_notification(
                    raw_data={
                        "title": "Document Verification Pending",
                        "message": f"Candidate document '{d.get('document_type', d['name'])}' is awaiting verification.",
                        "notification_type": "Reminder",
                        "priority": "Medium",
                        "category": "Candidate",
                        "entity_type": "Candidate Document",
                        "entity_id": d["name"],
                        "action_url": f"/candidates/{d.get('parent')}",
                        "action_label": "Verify Document",
                    },
                    company=None,
                    recipient=getattr(frappe.session, "user", "Administrator"),
                )
    except Exception as exc:
        frappe.logger().error(f"Error in send_pending_document_verification_reminders: {exc}")
