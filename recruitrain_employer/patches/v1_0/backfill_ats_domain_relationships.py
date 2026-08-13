# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

import frappe

def execute():
    """Phase 1 Data Migration Patch:
    Backfill missing relationships across Interview Feedback, Offer, and Candidate DocTypes non-destructively.
    """
    frappe.logger().info("Starting Phase 1 ATS domain relationship backfill...")

    # 1. Backfill Interview Feedback -> job_application & candidate
    if frappe.db.exists("DocType", "Interview Feedback"):
        feedbacks = frappe.get_all("Interview Feedback", fields=["name", "interview", "candidate", "job_application"])
        for fb in feedbacks:
            updates = {}
            if fb.interview and frappe.db.exists("Interview", fb.interview):
                int_doc = frappe.get_doc("Interview", fb.interview)
                if not fb.job_application and getattr(int_doc, "job_application", None):
                    updates["job_application"] = int_doc.job_application
                if getattr(int_doc, "candidate", None) and fb.candidate != int_doc.candidate:
                    updates["candidate"] = int_doc.candidate

            if updates:
                frappe.db.set_value("Interview Feedback", fb.name, updates, update_modified=False)

    # 2. Backfill Offer -> job_application, candidate, job_opening
    if frappe.db.exists("DocType", "Offer"):
        offers = frappe.get_all("Offer", fields=["name", "interview", "job_application", "candidate", "job_opening"])
        for offer in offers:
            updates = {}
            if not offer.job_application and offer.interview and frappe.db.exists("Interview", offer.interview):
                int_doc = frappe.get_doc("Interview", offer.interview)
                if getattr(int_doc, "job_application", None):
                    updates["job_application"] = int_doc.job_application

            target_app = updates.get("job_application") or offer.job_application
            if target_app and frappe.db.exists("Job Application", target_app):
                app_doc = frappe.get_doc("Job Application", target_app)
                if not offer.candidate and getattr(app_doc, "candidate", None):
                    updates["candidate"] = app_doc.candidate
                if not offer.job_opening and getattr(app_doc, "job_opening", None):
                    updates["job_opening"] = app_doc.job_opening

            if updates:
                frappe.db.set_value("Offer", offer.name, updates, update_modified=False)

    # 3. Synchronize Candidate legacy fields from latest Job Application
    if frappe.db.exists("DocType", "Candidate") and frappe.db.exists("DocType", "Job Application"):
        candidates = frappe.get_all("Candidate", fields=["name", "status"])
        status_map = {
            "Applied": "Active",
            "Screening": "In Review",
            "Shortlisted": "In Review",
            "Interview": "Interviewing",
            "Technical": "Interviewing",
            "HR": "Interviewing",
            "Offered": "Offered",
            "Hired": "Hired",
            "Rejected": "Rejected",
            "Withdrawn": "Archived",
        }
        for cand in candidates:
            latest_app = frappe.get_all(
                "Job Application",
                filters={"candidate": cand.name},
                fields=["current_stage", "status"],
                order_by="creation desc",
                limit=1,
            )
            if latest_app:
                stage = latest_app[0].get("current_stage") or latest_app[0].get("status")
                target_status = status_map.get(stage)
                if target_status and cand.status != target_status:
                    frappe.db.set_value("Candidate", cand.name, "status", target_status, update_modified=False)

    frappe.logger().info("Phase 1 ATS domain relationship backfill completed successfully.")
