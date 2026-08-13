# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.utils.activity_logger
===========================================
Centralized event logger for generating Activity Logs records across recruitment services.
"""

from __future__ import annotations
import frappe

def log_activity(
    activity_type: str,
    description: str,
    reference_doctype: str | None = None,
    reference_name: str | None = None,
    candidate: str | None = None,
    job_opening: str | None = None,
    job_application: str | None = None,
    company: str | None = None,
    performed_by: str | None = None,
    remarks: str | None = None,
) -> None:
    """Safely log a business activity entry in the Activity Logs DocType."""
    try:
        user = performed_by or getattr(frappe.session, "user", "System")
        if user == "Guest":
            user = "Administrator"

        doc = frappe.new_doc("Activity Logs")
        doc.activity_name = f"{activity_type} - {description[:30]}"
        doc.activity_type = activity_type if activity_type in [
            "Candidate Created", "Candidate Updated", "Job Published", "Job Updated",
            "Application Submitted", "Application Updated", "Interview Scheduled",
            "Interview Completed", "Interview Feedback Submitted", "Offer Sent",
            "Offer Accepted", "Offer Rejected", "Status Changed", "Document Uploaded",
            "Login", "Other"
        ] else "Other"
        doc.description = description
        doc.activity_date = frappe.utils.now_datetime()
        doc.performed_by = user
        if reference_doctype:
            doc.reference_doctype = reference_doctype
        if reference_name:
            doc.reference_name = reference_name
        if candidate:
            doc.candidate = candidate
        if job_opening:
            doc.job_opening = job_opening
        if job_application:
            doc.job_application = job_application
        if company:
            doc.company = company
        if remarks:
            doc.remarks = remarks

        doc.flags.ignore_permissions = True
        doc.insert()
    except Exception as exc:
        frappe.logger().error(f"Failed to log activity '{activity_type}': {exc}")
