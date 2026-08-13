# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

import frappe
from recruitrain_employer.services.talent_pool_service import TalentPoolService
from recruitrain_employer.utils.permissions import employer_required
from recruitrain_employer.utils.response import success_response, error_response
from recruitrain_employer.utils.exceptions import ATSException

def _handle_ats_exception(exc: Exception) -> dict:
    if isinstance(exc, ATSException):
        return error_response(code=exc.code, message=exc.message, details=exc.details, http_status_code=400)
    return error_response(code="INTERNAL_SERVER_ERROR", message=str(exc), http_status_code=500)

@frappe.whitelist()
@employer_required
def create_pool() -> dict:
    try:
        data = frappe.form_dict
        service = TalentPoolService()
        res = service.create_pool(data)
        return success_response(data=res, message="Talent Pool created successfully.")
    except Exception as exc:
        return _handle_ats_exception(exc)

@frappe.whitelist()
@employer_required
def list_pools() -> dict:
    try:
        service = TalentPoolService()
        data = service.list_pools()
        return success_response(data=data)
    except Exception as exc:
        return _handle_ats_exception(exc)

@frappe.whitelist()
@employer_required
def add_candidate() -> dict:
    try:
        pool_id = frappe.form_dict.get("pool_id")
        candidate_id = frappe.form_dict.get("candidate_id")
        notes = frappe.form_dict.get("notes")
        service = TalentPoolService()
        res = service.add_candidate_to_pool(pool_id, candidate_id, notes)
        return success_response(data=res, message="Candidate added to Talent Pool.")
    except Exception as exc:
        return _handle_ats_exception(exc)

@frappe.whitelist()
@employer_required
def remove_candidate() -> dict:
    try:
        pool_id = frappe.form_dict.get("pool_id")
        candidate_id = frappe.form_dict.get("candidate_id")
        service = TalentPoolService()
        res = service.remove_candidate_from_pool(pool_id, candidate_id)
        return success_response(data=res, message="Candidate removed from Talent Pool.")
    except Exception as exc:
        return _handle_ats_exception(exc)
