# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

import json
import frappe
from recruitrain_employer.services.job_application_service import JobApplicationService
from recruitrain_employer.services.candidate_service import CandidateService
from recruitrain_employer.utils.permissions import employer_required
from recruitrain_employer.utils.response import success_response, error_response
from recruitrain_employer.utils.exceptions import ATSException

def _parse_ids(val) -> list[str]:
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return [x.strip() for x in val.split(",") if x.strip()]
    return []

@frappe.whitelist()
@employer_required
def bulk_change_stage() -> dict:
    try:
        application_ids = _parse_ids(frappe.form_dict.get("application_ids"))
        new_stage = frappe.form_dict.get("new_stage") or frappe.form_dict.get("status")
        service = JobApplicationService()

        updated = []
        for app_id in application_ids:
            res = service.change_status(app_id, new_stage)
            updated.append(res["name"])

        return success_response(
            data={"updated_count": len(updated), "updated_ids": updated},
            message=f"Successfully moved {len(updated)} applications to '{new_stage}'."
        )
    except Exception as exc:
        return error_response(code="BULK_ERROR", message=str(exc), http_status_code=400)

@frappe.whitelist()
@employer_required
def bulk_archive_candidates() -> dict:
    try:
        candidate_ids = _parse_ids(frappe.form_dict.get("candidate_ids"))
        service = CandidateService()

        archived = []
        for cand_id in candidate_ids:
            service.update_candidate(cand_id, {"status": "Archived"})
            archived.append(cand_id)

        return success_response(
            data={"archived_count": len(archived), "archived_ids": archived},
            message=f"Successfully archived {len(archived)} candidates."
        )
    except Exception as exc:
        return error_response(code="BULK_ERROR", message=str(exc), http_status_code=400)

@frappe.whitelist()
@employer_required
def bulk_shortlist_applications() -> dict:
    try:
        application_ids = _parse_ids(frappe.form_dict.get("application_ids"))
        service = JobApplicationService()

        shortlisted = []
        for app_id in application_ids:
            res = service.change_status(app_id, "Shortlisted")
            shortlisted.append(res["name"])

        return success_response(
            data={"shortlisted_count": len(shortlisted), "shortlisted_ids": shortlisted},
            message=f"Successfully shortlisted {len(shortlisted)} applications."
        )
    except Exception as exc:
        return error_response(code="BULK_ERROR", message=str(exc), http_status_code=400)
