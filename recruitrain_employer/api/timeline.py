# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

import frappe
from recruitrain_employer.utils.permissions import employer_required
from recruitrain_employer.utils.response import success_response, error_response
from recruitrain_employer.utils.company_context import get_current_company

@frappe.whitelist()
@employer_required
def get_timeline() -> dict:
    """Retrieve full activity timeline for Candidate or Job Application."""
    candidate_id = frappe.form_dict.get("candidate_id") or frappe.form_dict.get("candidate")
    application_id = frappe.form_dict.get("application_id") or frappe.form_dict.get("job_application")
    company = get_current_company()

    filters = {}
    if company:
        filters["company"] = company
    if candidate_id:
        filters["candidate"] = candidate_id
    if application_id:
        filters["job_application"] = application_id

    logs = frappe.get_all(
        "Activity Logs",
        filters=filters,
        fields=[
            "name", "activity_name", "activity_type", "description",
            "activity_date", "performed_by", "candidate", "job_opening",
            "job_application", "company", "remarks", "creation"
        ],
        order_by="creation desc",
        limit=100,
    )
    return success_response(data=logs)
