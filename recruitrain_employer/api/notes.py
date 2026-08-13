# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

import frappe
from recruitrain_employer.services.note_service import CandidateNoteService
from recruitrain_employer.utils.permissions import employer_required
from recruitrain_employer.utils.response import success_response, error_response
from recruitrain_employer.utils.exceptions import ATSException

def _handle_ats_exception(exc: Exception) -> dict:
    if isinstance(exc, ATSException):
        return error_response(code=exc.code, message=exc.message, details=exc.details, http_status_code=400)
    return error_response(code="INTERNAL_SERVER_ERROR", message=str(exc), http_status_code=500)

@frappe.whitelist()
@employer_required
def add_note() -> dict:
    try:
        data = frappe.form_dict
        service = CandidateNoteService()
        res = service.add_note(data)
        return success_response(data=res, message="Note added successfully.")
    except Exception as exc:
        return _handle_ats_exception(exc)

@frappe.whitelist()
@employer_required
def list_notes(candidate_id: str | None = None) -> dict:
    try:
        cand_id = candidate_id or frappe.form_dict.get("candidate_id") or frappe.form_dict.get("candidate")
        service = CandidateNoteService()
        data = service.list_notes(cand_id)
        return success_response(data=data)
    except Exception as exc:
        return _handle_ats_exception(exc)

@frappe.whitelist()
@employer_required
def toggle_pin(note_id: str | None = None) -> dict:
    try:
        n_id = note_id or frappe.form_dict.get("note_id")
        service = CandidateNoteService()
        res = service.toggle_pin(n_id)
        return success_response(data=res, message="Note pin toggled successfully.")
    except Exception as exc:
        return _handle_ats_exception(exc)

@frappe.whitelist()
@employer_required
def delete_note(note_id: str | None = None) -> dict:
    try:
        n_id = note_id or frappe.form_dict.get("note_id")
        service = CandidateNoteService()
        service.delete_note(n_id)
        return success_response(message="Note deleted successfully.")
    except Exception as exc:
        return _handle_ats_exception(exc)
